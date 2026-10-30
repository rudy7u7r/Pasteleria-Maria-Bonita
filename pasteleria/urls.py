from django.urls import path
from . import views

urlpatterns = [
    # Páginas principales y catálogo
    path('', views.catalogo, name='catalogo'),
    path('producto/<int:id>/', views.detalle_producto, name='detalle_producto'),
    path('pedido-personalizado/', views.pedido_personalizado, name='pedido_personalizado'),

    # Autenticación
    path('login/', views.iniciar_sesion, name='login'),
    path('registro/', views.registrar_usuario, name='registro'),
    path('logout/', views.cerrar_sesion, name='logout'),

    # Panel Interno y CRUD de Productos (Exclusivo Administrador / Staff)
    path('panel-pastelero/', views.panel_pastelero, name='panel_pastelero'),
    path('gestion-productos/', views.gestion_productos, name='gestion_productos'),
    path('producto/renovar/<int:id>/', views.renovar_stock, name='renovar_stock'),
    path('producto/eliminar/<int:id>/', views.eliminar_producto, name='eliminar_producto'),
    path('producto/editar/<int:id>/', views.editar_producto, name='editar_producto'),

    # Carrito de Compras y Boletas (Exclusivo Clientes / No Staff)
    path('carrito/', views.ver_carrito, name='ver_carrito'),
    path('carrito/agregar/<int:id>/', views.agregar_al_carrito, name='agregar_al_carrito'),
    path('carrito/comprar/', views.procesar_compra, name='procesar_compra'),
    path('mis-boletas/', views.mis_boletas, name='mis_boletas'),
    path('comprar/<int:id>/', views.comprar_producto, name='comprar_producto'),
    path('', views.catalogo, name='catalogo'),
]