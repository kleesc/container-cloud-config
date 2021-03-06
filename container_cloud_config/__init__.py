"""
Provides helper methods and templates for generating cloud config for running containers.
"""

from functools import partial

import base64
import os
import requests
import logging
import urllib2
from jinja2 import FileSystemLoader, Environment, StrictUndefined

logger = logging.getLogger(__name__)

ETCD_DISCOVERY_URL = 'https://discovery.etcd.io/new'
COREOS_STACK_URL = 'http://{0}.release.core-os.net/amd64-usr/current/coreos_production_ami_{1}.txt'
FLAT_IMAGE_URL = 'https://{0}{1}/c1/squash{2}/{3}'
CHUNK_SIZE = 10 * 1024

class _PreventedRedirectException(urllib2.HTTPError):
  pass

class _PreventRedirects(urllib2.HTTPRedirectHandler):
  def redirect_request(self, req, fp, code, msg, hdrs, newurl):
    raise _PreventedRedirectException(newurl, code, 'Prevented redirect', hdrs, fp)

class CloudConfigContext(object):
  """ Context object for easy generating of cloud config. """
  def __init__(self, flat_image_template=None):
    self._flattened_urls_and_auth_strings = []
    self._flat_image_template = flat_image_template or FLAT_IMAGE_URL

  def populate_jinja_environment(self, env):
    """ Populates the given jinja environment with the methods defined in this context. """
    env.filters['registry'] = self.registry
    env.globals['flattened_url'] = self.flattened_url
    env.globals['new_etcd_discovery_token'] = self.new_etcd_discovery_token
    env.globals['load_coreos_ami'] = self.load_coreos_ami_id
    env.globals['dockersystemd'] = self._dockersystemd_template

  def _dockersystemd_template(self, name, container, username='', password='',
                              tag='latest', extra_args='', command='', after_units=[],
                              flattened=False, exec_start_post=[], exec_stop_post=[],
                              restart_policy='always', oneshot=False, env_file=None,
                              onfailure_units=[], requires_units=[], wants_units=[],
                              timeout_start_sec=None, timeout_stop_sec=None,
                              autostart=True):

    path = os.path.join(os.path.dirname(__file__), 'templates')
    env = Environment(loader=FileSystemLoader(path), undefined=StrictUndefined)
    self.populate_jinja_environment(env)
    template = env.get_template('dockersystemd.yaml')
    return template.render(name=name,
                           container=container,
                           username=username,
                           password=password,
                           tag=tag,
                           extra_args=extra_args,
                           command=command,
                           after_units=after_units,
                           requires_units=requires_units,
                           wants_units=wants_units,
                           flattened=flattened,
                           onfailure_units=onfailure_units,
                           exec_start_post=exec_start_post,
                           exec_stop_post=exec_stop_post,
                           restart_policy=restart_policy,
                           oneshot=oneshot,
                           autostart=autostart,
                           timeout_start_sec=timeout_start_sec,
                           timeout_stop_sec=timeout_stop_sec,
                           env_file=env_file)

  def new_etcd_discovery_token(self):
    """ Returns a new etcd discovery token. """
    token_req = requests.get(ETCD_DISCOVERY_URL)
    return token_req.text.split('/')[-1]

  def load_coreos_ami_id(self, coreos_channel, pv_or_hvm='hvm', aws_region='us-east-1'):
    """ Returns an AMI ID for a CoreOS AMI on the given channel. """
    stack_list_string = requests.get(COREOS_STACK_URL.format(coreos_channel, pv_or_hvm)).text
    stack_amis = dict([stack.split('=') for stack in stack_list_string.split('|')])
    return stack_amis[aws_region]

  def flattened_url(self, container_name, tag_name, username, password):
    """ Generates a URL for downloading a flattened container image. """
    registry_url = self.registry(container_name)
    if registry_url == '':
      raise Exception('Docker hub does not support flattened images')

    repository_path = container_name[(container_name.find('/')):]

    auth = ''
    if username and password:
      auth = '{0}:{1}@'.format(username, password)

    curl_url = self._flat_image_template.format(auth, registry_url, repository_path, tag_name)
    noauth_url = self._flat_image_template.format('', registry_url, repository_path, tag_name)
    self._flattened_urls_and_auth_strings.append((noauth_url, username, password))
    return curl_url

  def registry(self, container_name):
    """ Parse the registry from repositories of the following formats:
        quay.io/quay/quay:tagname -> quay.io
        localhost:5000/quay/quay:tagname -> localhost:5000
        localhost:5000/quay/quay -> localhost:5000
        quay/quay:latest -> ''
        quay/quay -> ''
        mysql:latest -> ''
        mysql -> ''
    """
    num_slashes = container_name.count('/')
    if num_slashes == 2:
      return container_name[:container_name.find('/')]
    else:
      return ''

  def prime_flattened_image_cache(self):
    """ Primes the cache for all flattened images requested by downloading them locally. """
    logger.debug('Priming flattened image cache with %s urls',
                 len(self._flattened_urls_and_auth_strings))
    for url, uname, passwd in self._flattened_urls_and_auth_strings:
      self._download_url(url, uname, passwd)

  def _download_url(self, url, username, password):
    """ Downloads the given URL. """
    logger.debug('Downloading url: %s', url)

    opener = urllib2.build_opener(_PreventRedirects)
    urllib2.install_opener(opener)

    req = urllib2.Request(url)
    if username and password:
      auth_string = ':'.join([username, password])
      req.add_unredirected_header('Authorization', 'Basic %s' % base64.b64encode(auth_string))

    try:
      flattened = urllib2.urlopen(req)
    except _PreventedRedirectException:
      logger.debug('Redirect indicates that URL is already cached.')
      return

    downloaded_bytes = 0
    last_whole_mb_reported = 0
    while True:
      chunk = flattened.read(CHUNK_SIZE)
      if not chunk:
        break

      downloaded_bytes += len(chunk)
      downloaded_mb = downloaded_bytes/1024.0/1024.0
      whole_mb_downloaded = int(downloaded_mb)

      if whole_mb_downloaded > last_whole_mb_reported:
        last_whole_mb_reported = whole_mb_downloaded
        logger.debug('Downloaded(MiB): %.1f' % downloaded_mb)

    logger.debug('Done downloading URL')
