from django.db import models, transaction
from django.db.models import F
from django.contrib.auth.models import User


METODOS_PAGO_CHOICES = [
    ('Debito', 'Tarjeta de Débito'),
    ('Credito', 'Tarjeta de Crédito'),
    ('Transferencia', 'Transferencia Bancaria'),
    ('Efectivo', 'Efectivo al recibir'),
]


class Cliente(models.Model):
    rut = models.CharField(max_length=12, unique=True)
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100, blank=True, null=True)
    telefono = models.CharField(max_length=15)
    email = models.EmailField(unique=True)
    direccion = models.CharField(max_length=200, blank=True, null=True)

    def __str__(self):
        return f"{self.nombre} ({self.rut})"


class Personal(models.Model):
    ROLES = [
        ('Pastelero', 'Pastelero'),
        ('Recepcionista', 'Recepcionista'),
        ('Administrador', 'Administrador'),
    ]

    rut = models.CharField(max_length=12, unique=True)
    nombre = models.CharField(max_length=100)
    telefono = models.CharField(max_length=15)
    rol = models.CharField(max_length=30, choices=ROLES, default='Pastelero')
    usuario = models.OneToOneField(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='perfil_personal',
    )

    def __str__(self):
        return f"{self.nombre} - {self.rol}"


class Producto(models.Model):
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True, null=True)
    precio_final = models.DecimalField(max_digits=10, decimal_places=2)
    stock = models.IntegerField(default=0)
    disponible = models.BooleanField(default=True)
    img = models.ImageField(upload_to='productos/', null=True, blank=True)

    def verificar_disponibilidad(self):
        return self.stock > 0

    def __str__(self):
        return self.nombre


class VentaStock(models.Model):
    ESTADOS_VENTA = [
        ('Pendiente', 'Pendiente de Revisión'),
        ('Aceptado', 'Pedido Aceptado'),
        ('Listo_Para_Entrega', 'Listo para Entrega'),
        ('Cancelado', 'Cancelado (Stock Devuelto)'),
    ]

    producto = models.ForeignKey(Producto, on_delete=models.CASCADE)
    cliente = models.ForeignKey(Cliente, on_delete=models.SET_NULL, null=True, blank=True)
    cantidad_comprada = models.IntegerField()
    estado = models.CharField(max_length=30, choices=ESTADOS_VENTA, default='Pendiente')

    def procesar_compra_directa(self):
        if not 1 <= self.cantidad_comprada <= 5:
            return False

        with transaction.atomic():
            producto_actualizado = Producto.objects.filter(
                pk=self.producto_id,
                stock__gte=self.cantidad_comprada,
            ).update(stock=F('stock') - self.cantidad_comprada)
            if not producto_actualizado:
                return False

            self.producto.refresh_from_db(fields=['stock'])
            self.producto.disponible = self.producto.stock > 0
            self.producto.save(update_fields=['disponible'])
            self.save()
        return True

    def devolver_stock_al_cancelar(self):
        if not 1 <= self.cantidad_comprada <= 5 or not self.producto_id:
            return False

        Producto.objects.filter(pk=self.producto_id).update(
            stock=F('stock') + self.cantidad_comprada,
            disponible=True,
        )
        return True


COSTO_DESPACHO_DOMICILIO = 3000

# --- Reglas de agenda para tortas personalizadas ---
CUPO_DIARIO_TORTAS = 5          # Máximo de tortas personalizadas que se entregan por día
ANTICIPACION_MINIMA_DIAS = 2    # La entrega debe ser al menos 2 días después de hoy (ej: pedido lunes -> desde miércoles)
HORA_APERTURA = 10              # Horario de entrega: desde las 10:00
HORA_CIERRE = 19                # ...hasta las 19:00 (inclusive)
UMBRAL_STOCK_BAJO = 2           # Productos con este stock o menos se consideran en alerta

TIPOS_ENTREGA_CHOICES = [
    ('Domicilio', 'Despacho a Domicilio'),
    ('Retiro', 'Retiro en Local'),
]


class PedidoPersonalizado(models.Model):
    PORCENTAJE_ABONO = 0.25

    ESTADOS_PEDIDO = [
        ('Pendiente_Coordinacion', 'En Revisión'),
        ('Aprobado_En_Produccion', 'En Preparación'),
        ('Listo_Para_Entrega', 'Lista - Va a su domicilio'),
        ('Entregado', 'Recibida por el Cliente'),
        ('Cancelado', 'Cancelada'),
    ]

    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, null=True, blank=True)
    personal = models.ForeignKey(Personal, on_delete=models.SET_NULL, null=True, blank=True)
    tipo_bizcocho = models.CharField(max_length=100)
    rellenos = models.CharField(max_length=100)
    coberturas = models.CharField(max_length=100)
    notas_decoracion = models.TextField()
    imagen_referencia = models.ImageField(upload_to='pedidos_referencia/', null=True, blank=True)
    tipo_entrega = models.CharField(
        max_length=20,
        choices=TIPOS_ENTREGA_CHOICES,
        default='Domicilio',
    )
    costo_envio = models.PositiveIntegerField(default=0)
    direccion_entrega = models.CharField(max_length=200, default='Por confirmar', blank=True)
    metodo_pago = models.CharField(
        max_length=30,
        choices=METODOS_PAGO_CHOICES,
        default='Debito',
    )
    porcentaje_abono = models.FloatField(default=PORCENTAJE_ABONO)
    monto_abono = models.FloatField()
    estado = models.CharField(
        max_length=50,
        choices=ESTADOS_PEDIDO,
        default='Pendiente_Coordinacion',
    )
    motivo_cancelacion = models.TextField(blank=True, default='')
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_entrega = models.DateTimeField()

    @property
    def precio_total(self):
        if self.porcentaje_abono:
            return round(self.monto_abono / self.porcentaje_abono)
        return round(self.monto_abono * 4)

    @property
    def saldo_pendiente(self):
        return max(0, round(self.precio_total - self.monto_abono))

    def calcular_abono_25(self, precio_total):
        self.porcentaje_abono = self.PORCENTAJE_ABONO
        self.monto_abono = precio_total * self.PORCENTAJE_ABONO
        return self.monto_abono

    @classmethod
    def pedidos_del_dia(cls, fecha):
        """Pedidos no cancelados cuya entrega cae en la fecha (día local) indicada."""
        return cls.objects.filter(fecha_entrega__date=fecha).exclude(estado='Cancelado')

    @classmethod
    def cupos_disponibles(cls, fecha, excluir_id=None):
        qs = cls.pedidos_del_dia(fecha)
        if excluir_id:
            qs = qs.exclude(id=excluir_id)
        return max(0, CUPO_DIARIO_TORTAS - qs.count())

    def validar_horario_entrega(self):
        """Retorna un mensaje de error si la fecha/hora no cumple las reglas, o None si es válida."""
        from django.utils import timezone
        ahora = timezone.now()
        entrega_local = timezone.localtime(self.fecha_entrega)

        if self.fecha_entrega <= ahora:
            return "La fecha de entrega no puede ser en el pasado. Seleccione una fecha y hora futuras."
        primer_dia = timezone.localdate() + timezone.timedelta(days=ANTICIPACION_MINIMA_DIAS)
        if entrega_local.date() < primer_dia:
            return (f"Las tortas personalizadas se deben pedir con al menos {ANTICIPACION_MINIMA_DIAS} días "
                    f"de anticipación. La primera fecha disponible es el {primer_dia.strftime('%d/%m/%Y')}.")
        minutos = entrega_local.hour * 60 + entrega_local.minute
        if minutos < HORA_APERTURA * 60 or minutos > HORA_CIERRE * 60:
            return (f"El horario de entrega es de {HORA_APERTURA:02d}:00 a {HORA_CIERRE:02d}:00 hrs. "
                    f"Seleccione una hora dentro de ese rango.")
        return None

    def validar_limites_agenda(self):
        """True si aún quedan cupos de producción para el día de entrega."""
        from django.utils import timezone
        dia = timezone.localtime(self.fecha_entrega).date()
        return self.cupos_disponibles(dia, excluir_id=self.pk) > 0

    def __str__(self):
        return f"Pedido Personalizado #{self.id} - {self.tipo_bizcocho}"


class Pago(models.Model):
    pedido_personalizado = models.ForeignKey(
        PedidoPersonalizado,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    monto_pago = models.FloatField()
    fecha_pago = models.DateTimeField(auto_now_add=True)
    estado_pago = models.CharField(max_length=50, default='Pendiente')

    def procesar_pasarela_pago(self):
        self.estado_pago = 'Aprobado'
        self.save()
        return True


class Mensaje(models.Model):
    pedido_personalizado = models.ForeignKey(
        PedidoPersonalizado,
        on_delete=models.CASCADE,
    )
    personal = models.ForeignKey(Personal, on_delete=models.SET_NULL, null=True, blank=True)
    contenido = models.TextField()
    fecha_envio = models.DateTimeField(auto_now_add=True)
    propuesta_alternativa = models.TextField(blank=True, null=True)

    def anadir_mensaje(self):
        self.save()

    def proponer_ajuste_diseno(self, propuesta):
        self.propuesta_alternativa = propuesta
        self.save()


# --- MODELOS: BOLETAS Y DETALLES DE COMPRA ---

class Boleta(models.Model):
    ESTADOS_BOLETA = [
        ('En_Revision', 'En Revisión'),
        ('En_Preparacion', 'En Preparación'),
        ('En_Camino', 'Lista - Va a su domicilio'),
        ('Recibida', 'Recibida por el Cliente'),
        ('Cancelada', 'Cancelada'),
    ]

    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, null=True, blank=True)
    tipo_entrega = models.CharField(
        max_length=20,
        choices=TIPOS_ENTREGA_CHOICES,
        default='Domicilio',
    )
    costo_envio = models.PositiveIntegerField(default=0)
    direccion_entrega = models.CharField(max_length=200, blank=True, null=True)
    metodo_pago = models.CharField(
        max_length=30,
        choices=METODOS_PAGO_CHOICES,
        default='Debito',
    )
    fecha = models.DateTimeField(auto_now_add=True)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    estado = models.CharField(max_length=30, choices=ESTADOS_BOLETA, default='En_Revision')
    motivo_cancelacion = models.TextField(blank=True, default='')

    @property
    def numero_formateado(self):
        return f"{self.id:03d}"

    def __str__(self):
        nombre_cliente = self.cliente.nombre if self.cliente else "Cliente"
        return f"Boleta N° {self.numero_formateado} - {nombre_cliente} ({self.get_estado_display()})"


class DetalleBoleta(models.Model):
    boleta = models.ForeignKey(Boleta, related_name='items', on_delete=models.CASCADE)
    producto = models.ForeignKey(Producto, on_delete=models.SET_NULL, null=True, blank=True)
    producto_nombre = models.CharField(max_length=100)
    cantidad = models.IntegerField(default=1)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.cantidad}x {self.producto_nombre} (Boleta #{self.boleta.id})"


class Resena(models.Model):
    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE)
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, null=True, blank=True, related_name='resenas')
    boleta = models.ForeignKey(Boleta, on_delete=models.CASCADE, null=True, blank=True, related_name='resenas')
    pedido_personalizado = models.ForeignKey(
        PedidoPersonalizado, on_delete=models.CASCADE, null=True, blank=True, related_name='resenas'
    )
    calificacion = models.PositiveSmallIntegerField(default=5)
    comentario = models.TextField(blank=True, default='')
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha']

    def __str__(self):
        return f"Reseña {self.calificacion}/5 - {self.cliente.nombre}"
