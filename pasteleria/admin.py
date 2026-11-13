from django.contrib import admin

from .models import (
    Boleta,
    Cliente,
    DetalleBoleta,
    Mensaje,
    Pago,
    PedidoPersonalizado,
    Personal,
    Producto,
    VentaStock,
)


class PagoInline(admin.TabularInline):
    model = Pago
    extra = 0


class MensajeInline(admin.TabularInline):
    model = Mensaje
    extra = 0


class DetalleBoletaInline(admin.TabularInline):
    model = DetalleBoleta
    extra = 0


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("id", "rut", "nombre", "apellido", "telefono", "email", "direccion")
    search_fields = ("rut", "nombre", "apellido", "email")


@admin.register(Personal)
class PersonalAdmin(admin.ModelAdmin):
    list_display = ("id", "rut", "nombre", "telefono", "rol")
    list_filter = ("rol",)
    search_fields = ("rut", "nombre")


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "precio_final", "stock", "disponible")
    list_filter = ("disponible",)
    search_fields = ("nombre", "descripcion")
    list_editable = ("precio_final", "stock")


@admin.register(VentaStock)
class VentaStockAdmin(admin.ModelAdmin):
    list_display = ("id", "producto", "cliente", "cantidad_comprada", "estado")
    list_select_related = ("producto", "cliente")
    list_filter = ("estado", "producto")
    search_fields = ("producto__nombre", "cliente__nombre", "cliente__rut")


@admin.register(PedidoPersonalizado)
class PedidoPersonalizadoAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "cliente",
        "personal",
        "tipo_bizcocho",
        "fecha_entrega",
        "monto_abono",
        "estado",
    )
    list_filter = ("estado", "fecha_entrega")
    search_fields = ("tipo_bizcocho", "rellenos", "coberturas", "cliente__nombre")
    inlines = (PagoInline, MensajeInline)


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ("id", "pedido_personalizado", "monto_pago", "estado_pago", "fecha_pago")
    list_filter = ("estado_pago", "fecha_pago")
    search_fields = ("pedido_personalizado__tipo_bizcocho",)
    list_select_related = ("pedido_personalizado",)


@admin.register(Mensaje)
class MensajeAdmin(admin.ModelAdmin):
    list_display = ("id", "pedido_personalizado", "personal", "fecha_envio", "propuesta_alternativa")
    search_fields = ("pedido_personalizado__tipo_bizcocho", "contenido")
    list_select_related = ("pedido_personalizado", "personal")


@admin.register(Boleta)
class BoletaAdmin(admin.ModelAdmin):
    list_display = ("id", "cliente", "fecha", "total", "estado")
    list_filter = ("estado", "fecha")
    search_fields = ("cliente__nombre", "cliente__rut", "cliente__email")
    inlines = (DetalleBoletaInline,)
