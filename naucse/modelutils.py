import logging
from collections import OrderedDict
from pathlib import Path
import sys

import yaml
from arca import Task, Arca

arca = Arca(settings={"ARCA_BACKEND_VERBOSITY": 2,
                      "ARCA_BACKEND_SINGLE_PULL": True,
                      "ARCA_CACHE_BACKEND": "dogpile.cache.memory"})

NOTHING = object()


class Model:
    def __init__(self, root, path):
        self.root = root
        self.path = Path(path)
        self.relative_path = self.path.relative_to(Path.cwd())

    def __str__(self):
        return '0x{:x}'.format(id(self))

    def __repr__(self):
        cls = type(self)
        return '<{}.{}: {}>'.format(cls.__module__, cls.__qualname__,
                                    str(self))


class LazyProperty:
    """Base class for a lazily computed property

    Subclasses should reimplement a `compute` method, which creates
    the value of the property. Then the value is stored and not computed again
    (unless deleted).
    """
    def __set_name__(self, cls, name):
        self.name = name

    def __get__(self, instance, cls):
        if instance is None:
            return self
        result = self.compute(instance)
        setattr(instance, self.name, result)
        return result

    def compute(self, instance):
        raise NotImplementedError()


class YamlProperty(LazyProperty):
    """Populated with the contents of a YAML file.

    If ``filename`` is not given, it is generated from the property's name.
    """
    def __init__(self, *, filename=None):
        self.filename = filename

    def compute(self, instance):
        filename = self.filename
        if filename is None:
            filename = self.name + '.yml'
        with instance.path.joinpath(filename).open(encoding='utf-8') as f:
            return yaml.safe_load(f)


class ForkProperty(LazyProperty):
    """ Populated from the fork the model is pointing to.

    ``repo`` and ``branch`` indicate from which attribute of the instance the property should take info about the fork.
    ``**kwargs`` are for `arca.Task` - the values can be callable (they get instance as a parameter)
    """
    def __init__(self, repo, branch, **kwargs):
        self.repo_prop = repo
        self.branch_prop = branch
        self.kwargs = kwargs

    def process_kwargs(self, instance):
        x = {}

        for key, value in self.kwargs.items():
            if callable(value):
                value = value(instance)

            x[key] = value

        return x

    def compute(self, instance):
        task = Task(**self.process_kwargs(instance))

        result = arca.run(getattr(instance, self.repo_prop.name), getattr(instance, self.branch_prop.name), task)

        try:
            logging.error(result.error)
        except AttributeError:
            pass

        return result.result


class DataProperty:
    """Value retrieved from a YamlProperty

    If ``key`` is not given, this property's name is used.
    """
    def __init__(self, dict_prop, *, key=NOTHING, default=NOTHING, convert=NOTHING):
        self.dict_prop = dict_prop
        self.key = key
        self.default = default
        self.convert = convert

    def __set_name__(self, cls, name):
        self.name = name

    def __get__(self, instance, cls):
        if instance is None:
            return self
        key = self.key
        if key is NOTHING:
            key = self.name
        info = getattr(instance, self.dict_prop.name)
        if self.default is NOTHING:
            val = info[key]
        else:
            val = info.get(key, self.default)

        if self.convert is NOTHING:
            return val

        return self.convert(val)


class DirProperty(LazyProperty):
    """Ordered dict of models from a subdirectory
    
    If ``info.yml`` is present in the subdirectory, use it for the order
    of the models.  The rest is appended alphabetically.
    """
    def __init__(self, cls, *subdir, keyfunc=str):
        self.cls = cls
        self.subdir = subdir
        self.keyfunc = keyfunc

    def get_ordered_paths(self, base):
        model_paths = []

        info_path = base.joinpath("info.yml")
        if info_path.is_file():
            with info_path.open(encoding='utf-8') as f:
                model_paths = [base.joinpath(p) for p in yaml.safe_load(f)['order']]

        remaining_subdirectories = [p for p in sorted(base.iterdir()) if p.is_dir() if p not in model_paths]

        return model_paths + remaining_subdirectories

    def compute(self, instance):
        base = instance.path.joinpath(*self.subdir)
        
        paths = self.get_ordered_paths(base)

        return OrderedDict(
            (self.keyfunc(p.parts[-1]), self.cls(instance.root, p))
            for p in paths
        )


class MultipleModelDirProperty(DirProperty):
    """ Ordered dict of models from a subdirectory

    Possible to order by ``info.yml`` just like DirProperty
    """
    def __init__(self, file_definition, *subdir, keyfunc=str):
        self.file_definition = file_definition
        super().__init__(file_definition.values(), *subdir, keyfunc=keyfunc)

    def compute(self, instance):
        base = instance.path.joinpath(*self.subdir)

        paths = self.get_ordered_paths(base)

        models = []

        for path in paths:  # type: Path
            cls = None
            for fl in path.iterdir():  # type: Path
                if not fl.is_file():
                    continue

                local_cls = self.file_definition.get(fl.name)
                if local_cls is not None:
                    if cls is not None:
                        raise ValueError(f"There are multiple definition files in {path.resolve()}")
                    cls = local_cls

            if cls is None:
                raise ValueError(f"There are no definition files in {path.resolve()}")

            models.append(
                (self.keyfunc(path.parts[-1]), cls(instance.root, path))
            )

        return OrderedDict(models)


class reify(LazyProperty):
    """Reify decorator, as known from Pyramid"""
    def __init__(self, func):
        self.compute = func


if sys.version_info < (3, 6):
    # Hack to make __set_name__ work in Python 3.5 and below
    class SettingDict(dict):
        def __setitem__(self, name, item):
            super().__setitem__(name, item)
            try:
                set_name = item.__set_name__
            except AttributeError:
                pass
            else:
                set_name(None, name)

    class ModelMeta(type):
        def __prepare__(meta, cls):
            return SettingDict()

    class Model(Model, metaclass=ModelMeta):
        pass
