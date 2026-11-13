from django.urls import path
from . import views

urlpatterns = [
    # Páginas principales y catálogo
    path('', views.catalogo, name='catalogo'),
    path('producto/<int:id>/', views.detalle_producto, name='detalle_producto'),

    # Tortas Personalizadas e Historial (Solo usuarios autenticados)
    path('pedido-personalizado/', views.pedido_personalizado, name='pedido_personalizado'),
    path('historial-tortas/', views.historial_personalizados, name='historial_personalizados'),
    path('pedido-personalizado/cancelar/<int:id>/', views.cancelar_pedido_personalizado, name='cancelar_pedido_personalizado'),
    path('pedido-personalizado/estado/<int:id>/', views.actualizar_estado_pedido, name='actualizar_estado_pedido'),
    path('pedido-personalizado/mensaje/<int:id>/', views.enviar_mensaje_pedido, name='enviar_mensaje_pedido'),
    path('pedido-personalizado/mensajes/<int:id>/', views.obtener_mensajes_pedido, name='obtener_mensajes_pedido'),
    path('mensajes/resumen/', views.resumen_notificaciones_mensajes, name='resumen_notificaciones_mensajes'),
    path('pedido-personalizado/editar-direccion/<int:id>/', views.editar_direccion_pedido_personalizado, name='editar_direccion_pedido_personalizado'),

    # Autenticación y Perfil
    path('login/', views.iniciar_sesion, name='login'),
    path('registro/', views.registrar_usuario, name='registro'),
    path('logout/', views.cerrar_sesion, name='logout'),
    path('mi-perfil/', views.perfil_cliente, name='perfil_cliente'),

    # Panel Interno y CRUD de Productos (Exclusivo Administrador / Staff)
    path('panel-pastelero/', views.panel_pastelero, name='panel_pastelero'),
    path('panel-pastelero/resumen-vivo/', views.panel_pastelero_resumen_vivo, name='panel_pastelero_resumen_vivo'),
    path('panel-pastelero/reporte-csv/', views.exportar_reporte_ventas, name='exportar_reporte_ventas'),
    path('panel-pastelero/personal/crear/', views.crear_personal, name='crear_personal'),
    path('panel-pastelero/asignar-rol/<int:id>/', views.asignar_rol_usuario, name='asignar_rol_usuario'),
    path('panel-pastelero/boleta/estado/<int:id>/', views.actualizar_estado_boleta, name='actualizar_estado_boleta'),
    path('gestion-productos/', views.gestion_productos, name='gestion_productos'),
    path('producto/renovar/<int:id>/', views.renovar_stock, name='renovar_stock'),
    path('producto/eliminar/<int:id>/', views.eliminar_producto, name='eliminar_producto'),
    path('producto/editar/<int:id>/', views.editar_producto, name='editar_producto'),

    # Carrito de Compras y Boletas
    path('carrito/', views.ver_carrito, name='ver_carrito'),
    path('carrito/agregar/<int:id>/', views.agregar_al_carrito, name='agregar_al_carrito'),
    path('carrito/restar/<int:id>/', views.restar_del_carrito, name='restar_del_carrito'),
    path('carrito/eliminar/<int:id>/', views.eliminar_del_carrito, name='eliminar_del_carrito'),
    path('carrito/vaciar/', views.vaciar_carrito, name='vaciar_carrito'),
    path('carrito/comprar/', views.procesar_compra, name='procesar_compra'),
    path('mis-boletas/', views.mis_boletas, name='mis_boletas'),
    path('boleta/editar-direccion/<int:id>/', views.editar_direccion_boleta, name='editar_direccion_boleta'),
    path('boleta/confirmar-recibida/<int:id>/', views.confirmar_boleta_recibida, name='confirmar_boleta_recibida'),
    path('boleta/resena/<int:id>/', views.crear_resena_boleta, name='crear_resena_boleta'),
    path('boleta/descargar/<int:id>/', views.descargar_boleta, name='descargar_boleta'),
    path('pedido-personalizado/confirmar-recibido/<int:id>/', views.confirmar_pedido_personalizado_recibido, name='confirmar_pedido_personalizado_recibido'),
    path('pedido-personalizado/resena/<int:id>/', views.crear_resena_pedido, name='crear_resena_pedido'),
    path('pedido-personalizado/descargar/<int:id>/', views.descargar_boleta_personalizada, name='descargar_boleta_personalizada'),
    path('comprar/<int:id>/', views.comprar_producto, name='comprar_producto'),
]
