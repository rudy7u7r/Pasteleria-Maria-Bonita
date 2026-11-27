#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    # Al iniciar el servidor (runserver) se aplican primero las migraciones pendientes,
    # así la base de datos queda lista sin tener que ejecutar "migrate" a mano.
    # RUN_MAIN evita repetirlo cuando el servidor se reinicia por cambios en el código.
    if len(sys.argv) > 1 and sys.argv[1] == 'runserver' and os.environ.get('RUN_MAIN') != 'true':
        execute_from_command_line([sys.argv[0], 'migrate', '--noinput'])

    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
