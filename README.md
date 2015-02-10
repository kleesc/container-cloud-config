# container-cloud-config
Module for helping to create cloud config for running containers

## Example

### Python code
    from container_cloud_config import CloudConfigContext
    from jinja2 import FileSystemLoader, Environment, StrictUndefined

    jinja_env = Environment(loader=FileSystemLoader('templates'), undefined=StrictUndefined)

    config_context = CloudConfigContext()
    config_context.populate_jinja_environment(jinja_env)

### Jinja template code
    # To retrieve an etcd discovery token:
    token={{ new_etcd_discovery_token() }}

    # To create systemd units for downloading and running a Docker image:
    {{ dockersystemd('myserver',
                     'quay.io/mynamespace/myservice',
                     'mynamespace+deploy',
                     'robottokenorpassword',
                     'latest',
                     extra_args='--privileged -p 443:443 -p 80:80',
                     after_units=[],
                     flattened=True
                    ) }}