from django.contrib import admin

from .models import Mensaje, Pago, PedidoPersonalizado, Producto, VentaStock


class PagoInline(admin.TabularInline):
    model = Pago
    extra = 0


class MensajeInline(admin.TabularInline):
    model = Mensaje
    extra = 0


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ("nombre", "precio_final", "stock", "disponible")
    list_filter = ("disponible",)
    search_fields = ("nombre", "descripcion")
    list_editable = ("precio_final", "stock")


@admin.register(VentaStock)
class VentaStockAdmin(admin.ModelAdmin):
    list_display = ("id", "producto", "cantidad_comprada")
    list_select_related = ("producto",)
    list_filter = ("producto",)
    search_fields = ("producto__nombre",)


@admin.register(PedidoPersonalizado)
class PedidoPersonalizadoAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tipo_bizcocho",
        "fecha_entrega",
        "monto_abono",
        "estado",
    )
    list_filter = ("estado", "fecha_entrega")
    search_fields = ("tipo_bizcocho", "rellenos", "coberturas")
    inlines = (PagoInline, MensajeInline)


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ("id", "pedido_personalizado", "monto_pago", "estado_pago", "fecha_pago")
    list_filter = ("estado_pago", "fecha_pago")
    search_fields = ("pedido_personalizado__tipo_bizcocho",)
    list_select_related = ("pedido_personalizado",)


@admin.register(Mensaje)
class MensajeAdmin(admin.ModelAdmin):
    list_display = ("id", "pedido_personalizado", "fecha_envio")
    search_fields = ("pedido_personalizado__tipo_bizcocho", "contenido")
    list_select_related = ("pedido_personalizado",)