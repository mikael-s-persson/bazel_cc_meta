import yaml


def yaml_safe_load(*args, **kwargs):
    return yaml.safe_load(*args, **kwargs)


def yaml_safe_load_all(*args, **kwargs):
    return yaml.safe_load_all(*args, **kwargs)


def yaml_safe_dump(*args, **kwargs):
    yaml.safe_dump(*args, **kwargs)
