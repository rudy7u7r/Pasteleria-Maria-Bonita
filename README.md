# Pastelería María Bonita

Tienda web de una pastelería artesanal hecha con **Django**. Los clientes pueden ver el catálogo, comprar con carrito, pedir tortas personalizadas y seguir sus pedidos; el personal administra todo desde un panel interno.

> Proyecto académico. Los pagos son **simulados**: no se conecta con ninguna pasarela de pago real.

## Funcionalidades

**Clientes**
- Catálogo con buscador, filtros, reseñas y detalle de cada torta.
- Carrito de compras con despacho a domicilio o retiro en local, y boleta en PDF.
- Tortas personalizadas: bizcocho, relleno, cobertura, imagen de referencia y chat con la pastelería.
  - Mínimo 2 días de anticipación, horario de entrega de 10:00 a 19:00 y máximo 5 tortas por día.
- Registro con validación de RUT (dígito verificador) y teléfono chileno, contraseña de mínimo 8 caracteres.
- Recuperación de contraseña por correo.

**Panel interno (personal)**
- Gestión de boletas y pedidos personalizados con cambio de estado en vivo.
- Calendario de entregas, gráficos de ventas y alerta de stock bajo.
- Gestión de productos, stock, personal y roles (Administrador, Pastelero, Recepcionista).
- Reporte de ventas en CSV.

## Requisitos

- Python 3.10 o superior
- Las librerías de `requirements.txt` (Django, Pillow y tzdata)

## Cómo ejecutarlo

1. Abra una terminal en la carpeta del proyecto.

2. Cree y active un entorno virtual nuevo:

   ```powershell
   python -m venv venv
   venv\Scripts\activate
   ```

   > La carpeta `venv` incluida en el repositorio se creó en otro computador y puede no funcionar en el suyo. Si el comando de arriba muestra un error o el entorno no arranca, borre la carpeta `venv` y vuelva a crearla con ese mismo comando.

3. Instale las dependencias:

   ```powershell
   pip install -r requirements.txt
   ```

4. Inicie el servidor:

   ```powershell
   python manage.py runserver
   ```

   Al iniciar, **las migraciones se aplican automáticamente**, así que no hace falta ejecutar `migrate` a mano.

5. Abra en el navegador: <http://127.0.0.1:8000>

## Datos incluidos

El repositorio incluye la base de datos `db.sqlite3` con los productos, usuarios y pedidos de prueba, y las fotos de los productos en `media/`.

Para entrar al panel interno use la cuenta de administrador `admin`. Si no tiene la contraseña, puede definir una nueva con:

```powershell
python manage.py changepassword admin
```

O crear un administrador propio:

```powershell
python manage.py createsuperuser
```

## Correos

En modo de desarrollo los correos (por ejemplo, el de recuperar contraseña) **no se envían de verdad**: se guardan como archivos en la carpeta `correos_enviados/`. Ábralos para ver el enlace y continuar el proceso.

## Pruebas

```powershell
python manage.py test pasteleria
```

## Estructura

```
config/                 Configuración del proyecto Django
pasteleria/             Aplicación principal
  models.py             Productos, pedidos, boletas, reseñas y reglas de agenda
  views.py              Lógica de las páginas
  validadores.py        Validación de RUT y teléfono chileno
  templates/            Páginas HTML
  static/               Estilos, scripts e ilustraciones
  tests.py              Pruebas automáticas
media/                  Fotos de los productos
manage.py               Comandos de Django (aplica migraciones al iniciar runserver)
```
