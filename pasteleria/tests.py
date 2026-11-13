from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
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


class PasteleriaFlujoTests(TestCase):
    def setUp(self):
        self.producto = Producto.objects.create(
            nombre="Torta Tres Leches",
            descripcion="Esponjosa torta con merengue italiano",
            precio_final=18000,
            stock=5,
            disponible=True,
        )

    def test_invitado_solo_guarda_en_carrito_y_no_ve_pedido_personalizado(self):
        resp_cat = self.client.get(reverse('catalogo'))
        self.assertEqual(resp_cat.status_code, 200)
        self.assertNotContains(resp_cat, "Solicitar Torta Personalizada")

        resp_ped = self.client.get(reverse('pedido_personalizado'))
        self.assertEqual(resp_ped.status_code, 302)
        self.assertIn('/login/', resp_ped.url)

        resp_add = self.client.post(reverse('comprar_producto', args=[self.producto.id]))
        self.assertEqual(resp_add.status_code, 302)
        self.assertEqual(self.client.session.get('carrito', {}).get(str(self.producto.id)), 1)

        resp_buy = self.client.post(reverse('procesar_compra'))
        self.assertEqual(resp_buy.status_code, 302)
        self.assertIn('/login/', resp_buy.url)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 5)
        self.assertEqual(Boleta.objects.count(), 0)

    def test_registro_usuario_crea_cliente_y_permite_comprar_y_personalizar(self):
        self.client.post(reverse('comprar_producto', args=[self.producto.id]))

        resp_reg = self.client.post(reverse('registro'), {
            'username': 'maria_bonita',
            'email': 'maria@ejemplo.com',
            'nombre': 'María',
            'apellido': 'Pérez',
            'rut': '18.123.456-7',
            'telefono': '+56987654321',
            'direccion': 'Av. Dulce 123',
            'password1': '1234',
            'password2': '1234',
            'next': '/carrito/',
        })
        self.assertRedirects(resp_reg, '/carrito/')
        self.assertEqual(User.objects.filter(username='maria_bonita').count(), 1)
        cliente = Cliente.objects.get(rut='18.123.456-7')

        resp_cat = self.client.get(reverse('catalogo'))
        self.assertContains(resp_cat, "Torta Personalizada")

        resp_buy = self.client.post(reverse('procesar_compra'))
        self.assertRedirects(resp_buy, reverse('ver_carrito'))
        boleta_creada = Boleta.objects.filter(cliente=cliente).first()
        self.assertIsNotNone(boleta_creada)
        self.assertEqual(boleta_creada.direccion_entrega, 'Av. Dulce 123')
        self.assertEqual(DetalleBoleta.objects.filter(producto=self.producto).count(), 1)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 4)

        resp_pers = self.client.post(reverse('pedido_personalizado'), {
            'bizcocho': 'Red Velvet',
            'relleno': 'Frambuesa y Manjar',
            'cobertura': 'Buttercream Pastel',
            'notas': 'Feliz Cumpleaños Sofía',
            'fecha_entrega': '2026-12-15',
            'hora_entrega': '17:30',
            'precio_estimado': '35000',
        })
        self.assertRedirects(resp_pers, reverse('historial_personalizados'))
        self.assertEqual(PedidoPersonalizado.objects.filter(cliente=cliente).count(), 1)
        self.assertEqual(Pago.objects.filter(estado_pago='Aprobado').count(), 1)

        pedido = PedidoPersonalizado.objects.first()
        self.client.post(reverse('enviar_mensaje_pedido', args=[pedido.id]), {
            'contenido': 'Por favor con flores rosadas',
        })
        self.assertEqual(Mensaje.objects.filter(pedido_personalizado=pedido).count(), 1)
        self.assertEqual(Personal.objects.count(), 0)

    def test_flujo_estados_boleta_y_confirmacion_cliente(self):
        cliente = Cliente.objects.create(
            rut="12.345.678-9",
            nombre="Carlos",
            apellido="Reyes",
            email="carlos@ejemplo.com",
            telefono="+56911223344"
        )
        boleta = Boleta.objects.create(
            cliente=cliente,
            total=18000,
            estado='En_Revision'
        )
        # Login de admin para cambiar estado
        admin_user = User.objects.create_superuser('admin_test', 'admin@test.cl', 'pass1234')
        self.client.login(username='admin_test', password='pass1234')

        # 1. Admin acepta pedido y pasa a En_Preparacion
        resp = self.client.post(reverse('actualizar_estado_boleta', args=[boleta.id]), {'estado': 'En_Preparacion'})
        self.assertEqual(resp.status_code, 302)
        boleta.refresh_from_db()
        self.assertEqual(boleta.estado, 'En_Preparacion')

        # 2. Admin marca como Lista - Va a su domicilio (En_Camino)
        self.client.post(reverse('actualizar_estado_boleta', args=[boleta.id]), {'estado': 'En_Camino'})
        boleta.refresh_from_db()
        self.assertEqual(boleta.estado, 'En_Camino')

        # 3. Cliente inicia sesión y confirma recepción
        user_carlos = User.objects.create_user('carlos', 'carlos@ejemplo.com', 'pass1234')
        self.client.login(username='carlos', password='pass1234')
        resp_conf = self.client.post(reverse('confirmar_boleta_recibida', args=[boleta.id]))
        self.assertEqual(resp_conf.status_code, 302)
        boleta.refresh_from_db()
        self.assertEqual(boleta.estado, 'Recibida')

        # 4. Una vez recibida, el admin no puede volver a editarla
        self.client.login(username='admin_test', password='pass1234')
        self.client.post(reverse('actualizar_estado_boleta', args=[boleta.id]), {'estado': 'En_Preparacion'})
        boleta.refresh_from_db()
        self.assertEqual(boleta.estado, 'Recibida')

    def test_flujo_estados_pedido_personalizado_y_chat(self):
        cliente = Cliente.objects.create(
            rut="11.222.333-4",
            nombre="Ana",
            apellido="Gómez",
            email="ana@ejemplo.com",
            telefono="+56999887766"
        )
        user_ana = User.objects.create_user('ana', 'ana@ejemplo.com', 'pass1234')
        from django.utils import timezone
        import datetime
        pedido = PedidoPersonalizado.objects.create(
            cliente=cliente,
            tipo_bizcocho="Chocolate",
            rellenos="Manjar",
            coberturas="Ganache",
            notas_decoracion="Temática dorada",
            monto_abono=10000,
            estado='Pendiente_Coordinacion',
            fecha_entrega=timezone.now() + datetime.timedelta(days=3)
        )

        admin_user = User.objects.create_superuser('admin_pastelero', 'admin2@test.cl', 'pass1234')
        self.client.login(username='admin_pastelero', password='pass1234')

        # Cliente edita dirección mientras está en revisión
        self.client.login(username='ana', password='pass1234')
        resp_dir = self.client.post(reverse('editar_direccion_pedido_personalizado', args=[pedido.id]), {
            'direccion_entrega': 'Calle Las Flores 456, Depto 101'
        })
        self.assertEqual(resp_dir.status_code, 302)
        pedido.refresh_from_db()
        self.assertEqual(pedido.direccion_entrega, 'Calle Las Flores 456, Depto 101')

        # Admin inicia sesión y también puede actualizar la dirección
        self.client.login(username='admin_pastelero', password='pass1234')
        self.client.post(reverse('editar_direccion_pedido_personalizado', args=[pedido.id]), {
            'direccion_entrega': 'Calle Las Flores 456, Depto 102'
        })
        pedido.refresh_from_db()
        self.assertEqual(pedido.direccion_entrega, 'Calle Las Flores 456, Depto 102')

        # Admin abre chat y envía mensaje al cliente
        resp_msg = self.client.post(reverse('enviar_mensaje_pedido', args=[pedido.id]), {
            'contenido': 'Hola Ana, ¿el ganache lo prefiere amargo o de leche?',
            'propuesta_alternativa': 'Ganache semi-amargo al 55%',
        })
        self.assertEqual(resp_msg.status_code, 302)
        self.assertEqual(Mensaje.objects.filter(pedido_personalizado=pedido).count(), 1)

        # Admin cambia estado a En Preparacion (Aprobado_En_Produccion)
        self.client.post(reverse('actualizar_estado_pedido', args=[pedido.id]), {'estado': 'Aprobado_En_Produccion'})
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'Aprobado_En_Produccion')

        # Admin cambia estado a Lista - Va a su domicilio (Listo_Para_Entrega)
        self.client.post(reverse('actualizar_estado_pedido', args=[pedido.id]), {'estado': 'Listo_Para_Entrega'})
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'Listo_Para_Entrega')

        # Una vez lista para entrega, la dirección ya NO es editable
        self.client.login(username='ana', password='pass1234')
        self.client.post(reverse('editar_direccion_pedido_personalizado', args=[pedido.id]), {
            'direccion_entrega': 'No Deberia Cambiar 999'
        })
        pedido.refresh_from_db()
        self.assertEqual(pedido.direccion_entrega, 'Calle Las Flores 456, Depto 102')

        # Cliente confirma recepción
        self.client.post(reverse('confirmar_pedido_personalizado_recibido', args=[pedido.id]))
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'Entregado')

    def test_ajax_chat_mensajes_tiempo_real(self):
        cliente = Cliente.objects.create(
            rut="15.999.888-7",
            nombre="Lucas",
            apellido="Valdés",
            email="lucas@test.com",
            telefono="+56911223344"
        )
        user_lucas = User.objects.create_user('lucas', 'lucas@test.com', 'pass1234')
        from django.utils import timezone
        import datetime
        pedido = PedidoPersonalizado.objects.create(
            cliente=cliente,
            tipo_bizcocho="Vainilla",
            rellenos="Crema Pastelera",
            coberturas="Chantilly",
            notas_decoracion="Aniversario",
            monto_abono=8000,
            estado='Pendiente_Coordinacion',
            fecha_entrega=timezone.now() + datetime.timedelta(days=2)
        )

        # 1. Cliente envía mensaje vía AJAX (sin recarga de página)
        self.client.login(username='lucas', password='pass1234')
        resp_ajax = self.client.post(reverse('enviar_mensaje_pedido', args=[pedido.id]), {
            'contenido': '¿Pueden agregar una vela temática?',
            'ajax': '1'
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp_ajax.status_code, 200)
        json_data = resp_ajax.json()
        self.assertEqual(json_data['status'], 'ok')
        self.assertIn('Lucas', json_data['mensaje']['emisor'])

        # 2. Endpoint de polling en tiempo real obtiene los mensajes y estado_display
        resp_poll = self.client.get(reverse('obtener_mensajes_pedido', args=[pedido.id]), HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(resp_poll.status_code, 200)
        data_poll = resp_poll.json()
        self.assertEqual(data_poll['status'], 'ok')
        self.assertEqual(data_poll['estado_display'], 'En Revisión')
        self.assertEqual(len(data_poll['mensajes']), 1)
        self.assertEqual(data_poll['mensajes'][0]['contenido'], '¿Pueden agregar una vela temática?')

        # 3. Admin consulta resumen de notificaciones y ve el mensaje del cliente
        admin_user = User.objects.create_superuser('admin_notif', 'admin_notif@test.cl', 'pass1234')
        self.client.login(username='admin_notif', password='pass1234')
        resp_resumen_admin = self.client.get(reverse('resumen_notificaciones_mensajes'))
        self.assertEqual(resp_resumen_admin.status_code, 200)
        res_admin = resp_resumen_admin.json()
        self.assertEqual(res_admin['status'], 'ok')
        self.assertIsNotNone(res_admin['ultimo_mensaje'])
        self.assertEqual(res_admin['ultimo_mensaje']['pedido_id'], pedido.id)

        # 4. Admin responde y cliente recibe notificación en su resumen
        self.client.post(reverse('enviar_mensaje_pedido', args=[pedido.id]), {
            'contenido': 'Claro que sí, la incluimos sin costo.',
            'ajax': '1'
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

        self.client.login(username='lucas', password='pass1234')
        resp_resumen_cli = self.client.get(reverse('resumen_notificaciones_mensajes'))
        self.assertEqual(resp_resumen_cli.status_code, 200)
        res_cli = resp_resumen_cli.json()
        self.assertIsNotNone(res_cli['ultimo_mensaje'])
        self.assertIn('Pastelería', res_cli['ultimo_mensaje']['emisor'])

    def test_perfil_cliente_actualiza_datos_y_direccion(self):
        cliente = Cliente.objects.create(
            rut="19.111.222-3",
            nombre="Sofía",
            apellido="Martínez",
            email="sofia@test.com",
            telefono="+56911111111",
            direccion="Dirección Antigua 100"
        )
        User.objects.create_user('sofia', 'sofia@test.com', 'pass1234', first_name='Sofía', last_name='Martínez')
        self.client.login(username='sofia', password='pass1234')

        resp = self.client.post(reverse('perfil_cliente'), {
            'nombre': 'Sofía Elena',
            'apellido': 'Martínez Soto',
            'telefono': '+56988776655',
            'direccion': 'Av. Nueva Providencia 2020',
        })
        self.assertRedirects(resp, reverse('perfil_cliente'))
        cliente.refresh_from_db()
        self.assertEqual(cliente.nombre, 'Sofía Elena')
        self.assertEqual(cliente.telefono, '+56988776655')
        self.assertEqual(cliente.direccion, 'Av. Nueva Providencia 2020')

    def test_descarga_boletas_pdf(self):
        from django.utils import timezone
        import datetime

        cliente = Cliente.objects.create(
            rut="16.555.444-3",
            nombre="Camila",
            apellido="Rojas",
            email="camila@test.com",
            telefono="+56922334455",
            direccion="Pasaje Dulce 45"
        )
        User.objects.create_user('camila', 'camila@test.com', 'pass1234')
        User.objects.create_user('otro_usuario', 'otro@test.com', 'pass1234')

        boleta = Boleta.objects.create(
            cliente=cliente,
            direccion_entrega="Pasaje Dulce 45",
            total=18000,
            estado='Recibida'
        )
        DetalleBoleta.objects.create(
            boleta=boleta,
            producto=self.producto,
            producto_nombre=self.producto.nombre,
            cantidad=1,
            precio_unitario=18000
        )

        pedido = PedidoPersonalizado.objects.create(
            cliente=cliente,
            tipo_bizcocho="Chocolate",
            rellenos="Frambuesa",
            coberturas="Ganache",
            notas_decoracion="Feliz Aniversario",
            direccion_entrega="Pasaje Dulce 45",
            monto_abono=10000,
            estado='Entregado',
            fecha_entrega=timezone.now() + datetime.timedelta(days=2)
        )

        # Otro usuario no puede descargar la boleta ajena
        self.client.login(username='otro_usuario', password='pass1234')
        resp_forbidden = self.client.get(reverse('descargar_boleta', args=[boleta.id]))
        self.assertEqual(resp_forbidden.status_code, 302)

        # La propietaria descarga ambas boletas en PDF
        self.client.login(username='camila', password='pass1234')
        resp_pdf = self.client.get(reverse('descargar_boleta', args=[boleta.id]))
        self.assertEqual(resp_pdf.status_code, 200)
        self.assertEqual(resp_pdf['Content-Type'], 'application/pdf')
        self.assertTrue(resp_pdf.content.startswith(b'%PDF-1.4'))
        self.assertIn(b'/Subtype /Image', resp_pdf.content)

        resp_pdf_pers = self.client.get(reverse('descargar_boleta_personalizada', args=[pedido.id]))
        self.assertEqual(resp_pdf_pers.status_code, 200)
        self.assertEqual(resp_pdf_pers['Content-Type'], 'application/pdf')
        self.assertTrue(resp_pdf_pers.content.startswith(b'%PDF-1.4'))
        self.assertIn(b'/Subtype /Image', resp_pdf_pers.content)

    def test_asignacion_roles_y_casillas_trabajador(self):
        cliente = Cliente.objects.create(
            rut="17.888.999-0",
            nombre="Diego",
            apellido="Silva",
            email="diego@test.com",
            telefono="+56933445566",
            direccion="Av. Pastel 88"
        )
        user_diego = User.objects.create_user('diego', 'diego@test.com', 'pass1234', first_name='Diego')
        User.objects.create_superuser('admin_roles', 'admin_roles@test.cl', 'pass1234')

        # Admin asigna rol Pastelero a Diego
        self.client.login(username='admin_roles', password='pass1234')
        resp_rol = self.client.post(reverse('asignar_rol_usuario', args=[cliente.id]), {'rol': 'Pastelero'})
        self.assertEqual(resp_rol.status_code, 302)

        user_diego.refresh_from_db()
        self.assertTrue(user_diego.is_staff)
        self.assertFalse(user_diego.is_superuser)
        personal_diego = Personal.objects.get(usuario=user_diego)
        self.assertEqual(personal_diego.rol, 'Pastelero')

        # Diego inicia sesión: accede a sus casillas en panel_pastelero pero no a gestion_productos ni Personal/Clientes
        self.client.login(username='diego', password='pass1234')
        resp_panel = self.client.get(reverse('panel_pastelero'))
        self.assertEqual(resp_panel.status_code, 200)
        self.assertContains(resp_panel, 'Rol activo: Pastelero')
        self.assertNotContains(resp_panel, 'Personal y Clientes')

        resp_stock = self.client.get(reverse('gestion_productos'))
        self.assertEqual(resp_stock.status_code, 302)

    def test_metodo_pago_en_compra_y_boleta(self):
        cliente = Cliente.objects.create(
            rut="14.222.333-5",
            nombre="Valentina",
            apellido="Cruz",
            email="val@test.com",
            telefono="+56944556677",
            direccion="Calle Dulzura 12"
        )
        User.objects.create_user('valentina', 'val@test.com', 'pass1234')
        self.client.login(username='valentina', password='pass1234')

        self.client.post(reverse('comprar_producto', args=[self.producto.id]))
        self.client.post(reverse('procesar_compra'), {'metodo_pago': 'Transferencia'})

        boleta = Boleta.objects.get(cliente=cliente)
        self.assertEqual(boleta.metodo_pago, 'Transferencia')

        resp_mis_boletas = self.client.get(reverse('mis_boletas'))
        self.assertContains(resp_mis_boletas, 'Transferencia Bancaria')

        # Torta personalizada con Tarjeta de Crédito
        self.client.post(reverse('pedido_personalizado'), {
            'bizcocho': 'Vainilla',
            'relleno': 'Manjar',
            'cobertura': 'Chantilly',
            'notas': 'Con flores',
            'fecha_entrega': '2026-12-20',
            'hora_entrega': '15:00',
            'precio_estimado': '25000',
            'metodo_pago': 'Credito',
        })
        pedido = PedidoPersonalizado.objects.get(cliente=cliente)
        self.assertEqual(pedido.metodo_pago, 'Credito')

    def test_procesar_compra_ajax_modal_json(self):
        self.client.post(reverse('registro'), {
            'username': 'ajax_buyer',
            'email': 'ajax@test.cl',
            'nombre': 'Comprador',
            'apellido': 'Ajax',
            'rut': '19.111.222-3',
            'telefono': '+56911111111',
            'direccion': 'Av. Test 123',
            'password1': 'pw1234',
            'password2': 'pw1234',
        })
        self.client.post(reverse('comprar_producto', args=[self.producto.id]))

        resp = self.client.post(
            reverse('procesar_compra'),
            {'metodo_pago': 'Debito', 'ajax': '1'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get('status'), 'ok')
        self.assertTrue(data.get('numero_boleta'))
        self.assertEqual(data.get('url_mis_boletas'), reverse('mis_boletas'))
        self.assertEqual(
            data.get('url_descargar_pdf'),
            reverse('descargar_boleta', args=[data.get('boleta_id')]),
        )

    def test_cancelacion_con_motivo_y_aviso_reembolso(self):
        self.client.post(reverse('registro'), {
            'username': 'cliente_cancel',
            'email': 'cancel@test.cl',
            'nombre': 'Lucía',
            'apellido': 'Gómez',
            'rut': '17.222.333-4',
            'telefono': '+56922222222',
            'direccion': 'Pasaje Los Pinos 45',
            'password1': 'pw1234',
            'password2': 'pw1234',
        })
        cliente = Cliente.objects.get(rut='17.222.333-4')
        self.client.post(reverse('comprar_producto', args=[self.producto.id]))
        self.client.post(reverse('procesar_compra'), {'metodo_pago': 'Debito'})
        boleta = Boleta.objects.get(cliente=cliente)

        self.client.post(reverse('pedido_personalizado'), {
            'bizcocho': 'Chocolate',
            'relleno': 'Frambuesa',
            'cobertura': 'Ganache',
            'notas': 'Sin nueces',
            'fecha_entrega': '2026-12-22',
            'hora_entrega': '16:00',
            'precio_estimado': '28000',
            'metodo_pago': 'Transferencia',
        })
        pedido = PedidoPersonalizado.objects.get(cliente=cliente)

        admin_user = User.objects.create_superuser(username='admin_cancel', email='admin@test.cl', password='pw')
        self.client.force_login(admin_user)

        # Intentar cancelar boleta sin motivo debe rechazar el cambio
        resp_sin_motivo = self.client.post(
            reverse('actualizar_estado_boleta', args=[boleta.id]),
            {'estado': 'Cancelada', 'motivo_cancelacion': ''},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp_sin_motivo.status_code, 400)
        boleta.refresh_from_db()
        self.assertNotEqual(boleta.estado, 'Cancelada')

        # Cancelar boleta con motivo válido
        motivo_boleta = 'Sin stock de ingredientes para la fecha solicitada'
        resp_boleta = self.client.post(
            reverse('actualizar_estado_boleta', args=[boleta.id]),
            {'estado': 'Cancelada', 'motivo_cancelacion': motivo_boleta},
        )
        self.assertEqual(resp_boleta.status_code, 302)
        boleta.refresh_from_db()
        self.assertEqual(boleta.estado, 'Cancelada')
        self.assertEqual(boleta.motivo_cancelacion, motivo_boleta)

        # Intentar cancelar pedido personalizado sin motivo debe rechazar el cambio
        resp_ped_sin_motivo = self.client.post(
            reverse('actualizar_estado_pedido', args=[pedido.id]),
            {'estado': 'Cancelado', 'motivo_cancelacion': '   '},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp_ped_sin_motivo.status_code, 400)
        pedido.refresh_from_db()
        self.assertNotEqual(pedido.estado, 'Cancelado')

        # Cancelar pedido personalizado con motivo válido
        motivo_pedido = 'Fuera de horario de cobertura de despacho'
        resp_ped = self.client.post(
            reverse('actualizar_estado_pedido', args=[pedido.id]),
            {'estado': 'Cancelado', 'motivo_cancelacion': motivo_pedido},
        )
        self.assertEqual(resp_ped.status_code, 302)
        pedido.refresh_from_db()
        self.assertEqual(pedido.estado, 'Cancelado')
        self.assertEqual(pedido.motivo_cancelacion, motivo_pedido)

        # El cliente ve el aviso de reembolso y el motivo en ambas vistas
        self.client.login(username='cliente_cancel', password='pw1234')
        resp_mis_boletas = self.client.get(reverse('mis_boletas'))
        self.assertContains(resp_mis_boletas, 'Se realizará reembolso')
        self.assertContains(resp_mis_boletas, motivo_boleta)

        resp_hist_ped = self.client.get(reverse('historial_personalizados'))
        self.assertContains(resp_hist_ped, 'Se realizará reembolso')
        self.assertContains(resp_hist_ped, motivo_pedido)

    def test_nuevas_funcionalidades_integrales(self):
        # Producto adicional para probar filtros y orden en catálogo
        prod_caro = Producto.objects.create(
            nombre="Torta Selva Negra",
            descripcion="Chocolate amargo con cerezas",
            precio_final=32000,
            stock=0,
            disponible=False,
        )

        # Buscador y filtros del catálogo
        resp_q = self.client.get(reverse('catalogo'), {'q': 'Selva'})
        self.assertContains(resp_q, 'Torta Selva Negra')
        self.assertNotContains(resp_q, 'Torta Tres Leches')

        resp_disp = self.client.get(reverse('catalogo'), {'disponible': '1'})
        self.assertContains(resp_disp, 'Torta Tres Leches')
        self.assertNotContains(resp_disp, 'Torta Selva Negra')

        # Registro de cliente y compra para probar stock, notificaciones, reseñas y perfil
        self.client.post(reverse('registro'), {
            'username': 'cliente_full',
            'email': 'full@test.cl',
            'nombre': 'Camila',
            'apellido': 'Díaz',
            'rut': '16.555.666-7',
            'telefono': '+56933333333',
            'direccion': 'Av. Flores 789',
            'password1': 'pw1234',
            'password2': 'pw1234',
        })
        cliente = Cliente.objects.get(rut='16.555.666-7')

        # Compra 2 unidades de self.producto (stock inicial 5 -> queda en 3)
        self.client.post(reverse('comprar_producto', args=[self.producto.id]))
        self.client.post(reverse('comprar_producto', args=[self.producto.id]))
        self.client.post(reverse('procesar_compra'), {'metodo_pago': 'Credito'})
        boleta1 = Boleta.objects.get(cliente=cliente)
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 3)

        # Verificar que resumen_notificaciones_mensajes incluye boletas_estados
        resp_notif = self.client.get(reverse('resumen_notificaciones_mensajes'))
        self.assertEqual(resp_notif.status_code, 200)
        self.assertEqual(len(resp_notif.json().get('boletas_estados', [])), 1)

        # Actualizar perfil y contraseña
        resp_perfil = self.client.post(reverse('perfil_cliente'), {
            'nombre': 'Camila',
            'apellido': 'Díaz',
            'email': 'camila_nueva@test.cl',
            'telefono': '+56944444444',
            'direccion': 'Calle Nueva 101',
            'password_actual': 'pw1234',
            'password_nueva': 'nueva1234',
            'password_confirmar': 'nueva1234',
        })
        self.assertEqual(resp_perfil.status_code, 302)
        cliente.refresh_from_db()
        self.assertEqual(cliente.email, 'camila_nueva@test.cl')
        self.assertTrue(User.objects.get(username='cliente_full').check_password('nueva1234'))

        # Admin cancela boleta1 -> debe restaurar el stock a 5 y mostrar métricas/CSV
        admin_user = User.objects.create_superuser(username='admin_full', email='adminfull@test.cl', password='pw')
        self.client.force_login(admin_user)
        self.client.post(
            reverse('actualizar_estado_boleta', args=[boleta1.id]),
            {'estado': 'Cancelada', 'motivo_cancelacion': 'Cliente solicitó anulación'},
        )
        self.producto.refresh_from_db()
        self.assertEqual(self.producto.stock, 5)
        self.assertTrue(self.producto.disponible)

        resp_panel = self.client.get(reverse('panel_pastelero'))
        self.assertEqual(resp_panel.status_code, 200)
        self.assertContains(resp_panel, 'Métricas y Ventas')

        resp_csv = self.client.get(reverse('exportar_reporte_ventas'))
        self.assertEqual(resp_csv.status_code, 200)
        self.assertIn('text/csv', resp_csv['Content-Type'])

        # Nueva compra recibida -> permite dejar reseña y se ve en detalle_producto
        self.client.login(username='cliente_full', password='nueva1234')
        self.client.post(reverse('comprar_producto', args=[self.producto.id]))
        self.client.post(reverse('procesar_compra'), {'metodo_pago': 'Debito'})
        boleta2 = Boleta.objects.filter(cliente=cliente).exclude(id=boleta1.id).first()
        boleta2.estado = 'Recibida'
        boleta2.save(update_fields=['estado'])

        resp_resena = self.client.post(reverse('crear_resena_boleta', args=[boleta2.id]), {
            'calificacion': '5',
            'comentario': 'Deliciosa y muy fresca',
        })
        self.assertEqual(resp_resena.status_code, 302)

        resp_det = self.client.get(reverse('detalle_producto', args=[self.producto.id]))
        self.assertContains(resp_det, 'Deliciosa y muy fresca')

    def test_entrega_retiro_imagen_referencia_y_panel_vivo(self):
        self.client.post(reverse('registro'), {
            'username': 'cliente_retiro',
            'email': 'retiro@test.cl',
            'nombre': 'Sofía',
            'apellido': 'Mora',
            'rut': '15.444.555-6',
            'telefono': '+56955555555',
            'direccion': 'Av. Central 500',
            'password1': 'pw1234',
            'password2': 'pw1234',
        })
        cliente = Cliente.objects.get(rut='15.444.555-6')

        # Compra con Retiro en Local (envío $0)
        self.client.post(reverse('comprar_producto', args=[self.producto.id]))
        self.client.post(reverse('procesar_compra'), {
            'metodo_pago': 'Debito',
            'tipo_entrega': 'Retiro',
        })
        boleta_retiro = Boleta.objects.get(cliente=cliente)
        self.assertEqual(boleta_retiro.tipo_entrega, 'Retiro')
        self.assertEqual(boleta_retiro.costo_envio, 0)
        self.assertEqual(boleta_retiro.direccion_entrega, 'Retiro en Local')
        self.assertEqual(int(boleta_retiro.total), 18000)

        # Pedido personalizado con imagen de referencia y despacho a domicilio
        gif_bytes = (
            b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00'
            b'\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00'
            b'\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        )
        img_ref = SimpleUploadedFile('ref_torta.gif', gif_bytes, content_type='image/gif')
        self.client.post(reverse('pedido_personalizado'), {
            'bizcocho': 'Vainilla Tradicional',
            'relleno': 'Manjar',
            'cobertura': 'Chantilly',
            'notas': 'Con flores',
            'fecha_entrega': '2026-12-28',
            'hora_entrega': '16:00',
            'precio_estimado': '25000',
            'metodo_pago': 'Transferencia',
            'tipo_entrega': 'Domicilio',
            'imagen_referencia': img_ref,
        })
        pedido = PedidoPersonalizado.objects.get(cliente=cliente)
        self.assertEqual(pedido.tipo_entrega, 'Domicilio')
        self.assertEqual(pedido.costo_envio, 3000)
        self.assertTrue(bool(pedido.imagen_referencia))

        # Admin: estado AJAX sin recarga y endpoint resumen vivo
        admin_user = User.objects.create_superuser(username='admin_vivo', email='adminvivo@test.cl', password='pw')
        self.client.force_login(admin_user)

        resp_vivo = self.client.get(reverse('panel_pastelero_resumen_vivo'))
        self.assertEqual(resp_vivo.status_code, 200)
        data_vivo = resp_vivo.json()
        self.assertEqual(data_vivo.get('status'), 'ok')
        self.assertGreaterEqual(data_vivo.get('boletas_count', 0), 1)
        self.assertGreaterEqual(data_vivo.get('pedidos_count', 0), 1)

        resp_ajax_estado = self.client.post(
            reverse('actualizar_estado_boleta', args=[boleta_retiro.id]),
            {'estado': 'En_Preparacion', 'ajax': '1'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(resp_ajax_estado.status_code, 200)
        self.assertEqual(resp_ajax_estado.json().get('nuevo_estado'), 'En_Preparacion')
