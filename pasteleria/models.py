from django.db import models, transaction
from django.db.models import F
from django.contrib.auth.models import User


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
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE)
    cliente = models.ForeignKey(Cliente, on_delete=models.SET_NULL, null=True, blank=True)
    cantidad_comprada = models.IntegerField()

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


class PedidoPersonalizado(models.Model):
    PORCENTAJE_ABONO = 0.25

    ESTADOS_PEDIDO = [
        ('Pendiente_Coordinacion', 'Pendiente de Coordinación'),
        ('Aprobado_En_Produccion', 'Aprobado en Producción'),
        ('Listo_Para_Entrega', 'Listo para Entrega'),
        ('Entregado', 'Entregado'),
        ('Cancelado', 'Cancelado'),
    ]

    cliente = models.ForeignKey(Cliente, on_delete=models.CASCADE, null=True, blank=True)
    personal = models.ForeignKey(Personal, on_delete=models.SET_NULL, null=True, blank=True)
    tipo_bizcocho = models.CharField(max_length=100)
    rellenos = models.CharField(max_length=100)
    coberturas = models.CharField(max_length=100)
    notas_decoracion = models.TextField()
    porcentaje_abono = models.FloatField(default=PORCENTAJE_ABONO)
    monto_abono = models.FloatField()
    estado = models.CharField(
        max_length=50,
        choices=ESTADOS_PEDIDO,
        default='Pendiente_Coordinacion',
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_entrega = models.DateTimeField()

    def calcular_abono_25(self, precio_total):
        self.porcentaje_abono = self.PORCENTAJE_ABONO
        self.monto_abono = precio_total * self.PORCENTAJE_ABONO
        return self.monto_abono

    def validar_limites_agenda(self):
        return True

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


# --- NUEVOS MODELOS: BOLETAS Y DETALLES DE COMPRA ---

class Boleta(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    fecha = models.DateTimeField(auto_now_add=True)
    total = models.DecimalField(max_digits=10, decimal_places=2)
    
    def __str__(self):
        return f"Boleta #{self.id} - {self.usuario.username}"


class DetalleBoleta(models.Model):
    boleta = models.ForeignKey(Boleta, related_name='items', on_delete=models.CASCADE)
    producto_nombre = models.CharField(max_length=100)
    cantidad = models.IntegerField(default=1)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return f"{self.cantidad}x {self.producto_nombre} (Boleta #{self.boleta.id})"