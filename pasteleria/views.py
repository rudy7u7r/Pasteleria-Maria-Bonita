import csv
from django.http import HttpResponse, JsonResponse
from datetime import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate, update_session_auth_hash
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.db.models import Avg, Count, F, Q, Sum
from django.utils import timezone
from .pdf_utils import construir_pdf_boleta
from .models import (
    Boleta,
    Cliente,
    COSTO_DESPACHO_DOMICILIO,
    DetalleBoleta,
    Mensaje,
    METODOS_PAGO_CHOICES,
    Pago,
    PedidoPersonalizado,
    Personal,
    Producto,
    Resena,
    TIPOS_ENTREGA_CHOICES,
    VentaStock,
)


# --- Helpers para vincular la sesión autenticada con los modelos Cliente y Personal ---

def _obtener_o_crear_cliente(user, rut=None, nombre=None, apellido=None, telefono=None, direccion=None):
    """Obtiene o crea el registro Cliente asociado al usuario autenticado."""
    if not user or not user.is_authenticated:
        return None

    email_usuario = (user.email or f"{user.username}@mariabonita.cl").strip().lower()
    if not user.email:
        user.email = email_usuario
        user.save(update_fields=['email'])

    cliente = Cliente.objects.filter(email__iexact=email_usuario).first()

    if not cliente and rut:
        cliente = Cliente.objects.filter(rut__iexact=rut.strip()).first()

    direccion_limpia = direccion.strip() if direccion else ""

    if not cliente:
        rut_final = (rut or f"CLI-{user.id:06d}").strip()[:12]
        if Cliente.objects.filter(rut=rut_final).exists():
            rut_final = f"C-{user.id}-{timezone.now().strftime('%M%S')}"[:12]

        if Cliente.objects.filter(email=email_usuario).exists():
            email_usuario = f"{user.username}.{user.id}@mariabonita.cl"

        cliente = Cliente.objects.create(
            rut=rut_final,
            nombre=(nombre or user.first_name or user.username)[:100],
            apellido=(apellido or user.last_name or "")[:100],
            telefono=(telefono or "+56900000000")[:15],
            email=email_usuario,
            direccion=direccion_limpia or "Por confirmar",
        )
    else:
        actualizado = False
        if nombre and not cliente.nombre:
            cliente.nombre = nombre[:100]
            actualizado = True
        if apellido and not cliente.apellido:
            cliente.apellido = apellido[:100]
            actualizado = True
        if telefono and cliente.telefono == "+56900000000":
            cliente.telefono = telefono[:15]
            actualizado = True
        if direccion_limpia and (not cliente.direccion or cliente.direccion == "Por confirmar"):
            cliente.direccion = direccion_limpia[:200]
            actualizado = True
        if actualizado:
            cliente.save()

    return cliente


def _obtener_o_crear_personal(user):
    """Obtiene o crea el registro Personal para un miembro del staff."""
    if not user or not user.is_authenticated or not user.is_staff:
        return None

    personal = Personal.objects.filter(usuario=user).first()
    if not personal:
        rut_staff = f"STF-{user.id:06d}"[:12]
        personal = Personal.objects.filter(rut=rut_staff).first()
        if personal and not personal.usuario_id:
            personal.usuario = user
            personal.save(update_fields=['usuario'])
    if not personal:
        personal = Personal.objects.create(
            rut=f"STF-{user.id:06d}"[:12],
            nombre=user.get_full_name() or user.username,
            telefono="+56911111111",
            rol="Administrador" if user.is_superuser else "Pastelero",
            usuario=user,
        )
    return personal


def _obtener_rol_staff(user):
    if not user or not user.is_authenticated or not user.is_staff:
        return None
    if user.is_superuser:
        return 'Administrador'
    personal = Personal.objects.filter(usuario=user).first()
    return personal.rol if personal else 'Pastelero'


# --- Vistas públicas y Catálogo ---

def catalogo(request):
    q = request.GET.get('q', '').strip()
    solo_disponibles = request.GET.get('disponible', '') == '1'
    orden = request.GET.get('orden', '').strip()

    productos = Producto.objects.annotate(
        promedio_calificacion=Avg('resenas__calificacion'),
        total_resenas=Count('resenas'),
    )
    if q:
        productos = productos.filter(Q(nombre__icontains=q) | Q(descripcion__icontains=q))
    if solo_disponibles:
        productos = productos.filter(stock__gt=0, disponible=True)

    if orden == 'precio_asc':
        productos = productos.order_by('precio_final', 'id')
    elif orden == 'precio_desc':
        productos = productos.order_by('-precio_final', 'id')
    else:
        productos = productos.order_by('id')

    return render(request, "pasteleria/catalogo.html", {
        "productos": productos,
        "q": q,
        "solo_disponibles": solo_disponibles,
        "orden": orden,
    })


def detalle_producto(request, id):
    producto = get_object_or_404(Producto, id=id)
    resenas = producto.resenas.select_related('cliente').all()
    promedio_calificacion = resenas.aggregate(prom=Avg('calificacion'))['prom']
    return render(request, "pasteleria/detalle_producto.html", {
        "producto": producto,
        "resenas": resenas,
        "promedio_calificacion": promedio_calificacion,
    })


# --- Tortas Personalizadas e Historial (Exclusivo Clientes con Sesión Iniciada) ---

def pedido_personalizado(request):
    if not request.user.is_authenticated:
        messages.warning(request, "Debe iniciar sesión o registrarse para diseñar y solicitar una torta personalizada.")
        return redirect(f"/login/?next={request.path}")
    if request.user.is_staff:
        return redirect('panel_pastelero')

    cliente_actual = _obtener_o_crear_cliente(request.user)

    if request.method == 'POST':
        bizcocho = request.POST.get('bizcocho', '').strip()
        relleno = request.POST.get('relleno', '').strip()
        cobertura = request.POST.get('cobertura', '').strip()
        notas = request.POST.get('notas', '').strip()
        fecha_str = request.POST.get('fecha_entrega', '').strip()
        hora_str = request.POST.get('hora_entrega', '').strip() or '16:00'
        precio_str = request.POST.get('precio_estimado', '25000').strip()

        try:
            precio_estimado = float(precio_str)
            if precio_estimado <= 0:
                precio_estimado = 25000.0
        except ValueError:
            precio_estimado = 25000.0

        try:
            dt_naive = datetime.strptime(f"{fecha_str} {hora_str}", "%Y-%m-%d %H:%M")
            fecha_entrega = timezone.make_aware(dt_naive) if timezone.is_naive(dt_naive) else dt_naive
        except ValueError:
            fecha_entrega = timezone.now() + timezone.timedelta(days=2)

        tipos_entrega_validos = dict(TIPOS_ENTREGA_CHOICES).keys()
        tipo_entrega = request.POST.get('tipo_entrega', 'Domicilio').strip()
        if tipo_entrega not in tipos_entrega_validos:
            tipo_entrega = 'Domicilio'
        costo_envio = COSTO_DESPACHO_DOMICILIO if tipo_entrega == 'Domicilio' else 0

        direccion_pedido = request.POST.get('direccion_entrega', '').strip()
        if tipo_entrega == 'Retiro':
            direccion_pedido = 'Retiro en Local'
        else:
            if not direccion_pedido and cliente_actual:
                direccion_pedido = (cliente_actual.direccion or '').strip()
            if not direccion_pedido or direccion_pedido.lower() == 'por confirmar':
                direccion_pedido = 'Por confirmar'

        metodos_validos = dict(METODOS_PAGO_CHOICES).keys()
        metodo_pago = request.POST.get('metodo_pago', 'Debito').strip()
        if metodo_pago not in metodos_validos:
            metodo_pago = 'Debito'

        imagen_referencia = request.FILES.get('imagen_referencia')

        pedido = PedidoPersonalizado(
            cliente=cliente_actual,
            tipo_bizcocho=bizcocho or 'Vainilla Tradicional',
            rellenos=relleno or 'Manjar artesanal',
            coberturas=cobertura or 'Chantilly suave',
            notas_decoracion=notas or 'Decoración clásica María Bonita',
            imagen_referencia=imagen_referencia,
            tipo_entrega=tipo_entrega,
            costo_envio=costo_envio,
            direccion_entrega=direccion_pedido,
            metodo_pago=metodo_pago,
            estado='Pendiente_Coordinacion',
            fecha_entrega=fecha_entrega,
        )
        monto_abono = round(pedido.calcular_abono_25(precio_estimado))
        pedido.monto_abono = monto_abono

        if not pedido.validar_limites_agenda():
            messages.error(request, "No hay disponibilidad en la agenda para la fecha seleccionada.")
            return redirect('pedido_personalizado')

        pedido.save()

        pago = Pago.objects.create(
            pedido_personalizado=pedido,
            monto_pago=monto_abono,
            estado_pago='Pendiente',
        )
        pago.procesar_pasarela_pago()

        messages.success(
            request,
            f"Su solicitud de Torta Personalizada #{pedido.id} ({pedido.tipo_bizcocho}) ha sido confirmada. "
            f"Abono registrado: ${int(monto_abono):,}".replace(",", ".")
        )
        return redirect('historial_personalizados')

    return render(request, "pasteleria/pedido_personalizado.html", {
        "cliente": cliente_actual,
    })


def historial_personalizados(request):
    if not request.user.is_authenticated:
        messages.warning(request, "Inicie sesión para revisar su historial de tortas personalizadas.")
        return redirect(f"/login/?next={request.path}")
    if request.user.is_staff:
        return redirect('panel_pastelero')

    cliente = _obtener_o_crear_cliente(request.user)
    pedidos = (
        PedidoPersonalizado.objects
        .prefetch_related('mensaje_set', 'pago_set')
        .select_related('cliente', 'personal')
        .filter(cliente=cliente)
        .order_by('-fecha_creacion')
    )

    return render(request, "pasteleria/historial_personalizados.html", {
        "pedidos": pedidos,
    })


def cancelar_pedido_personalizado(request, id):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.method == 'POST':
        pedido = get_object_or_404(PedidoPersonalizado, id=id)
        cliente = _obtener_o_crear_cliente(request.user)
        es_propietario = (cliente and pedido.cliente_id == cliente.id) or request.user.is_staff

        if es_propietario and pedido.estado == 'Pendiente_Coordinacion':
            pedido.estado = 'Cancelado'
            pedido.save()
            messages.info(request, f"La solicitud de Torta Personalizada #{pedido.id} ha sido cancelada.")
    return redirect('historial_personalizados')


def confirmar_pedido_personalizado_recibido(request, id):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.method == 'POST':
        pedido = get_object_or_404(PedidoPersonalizado, id=id)
        cliente = _obtener_o_crear_cliente(request.user)
        es_propietario = (cliente and pedido.cliente_id == cliente.id) or request.user.is_staff

        if es_propietario:
            if pedido.estado == 'Listo_Para_Entrega':
                pedido.estado = 'Entregado'
                pedido.save(update_fields=['estado'])
                messages.success(request, f"¡Gracias! Ha confirmado la recepción de su Torta Personalizada #{pedido.id}. El pedido ha quedado finalizado.")
            elif pedido.estado == 'Entregado':
                messages.info(request, "Este pedido ya fue confirmado como recibido previamente.")
            else:
                messages.warning(request, "Solo puede confirmar recepción cuando el pedido se encuentre listo para entrega.")
    return redirect('historial_personalizados')


def enviar_mensaje_pedido(request, id):
    if not request.user.is_authenticated:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == '1':
            return JsonResponse({'status': 'error', 'message': 'No autenticado'}, status=401)
        return redirect('login')

    if request.method == 'POST':
        pedido = get_object_or_404(PedidoPersonalizado, id=id)
        contenido = request.POST.get('contenido', '').strip()
        propuesta = request.POST.get('propuesta_alternativa', '').strip()
        es_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == '1' or 'application/json' in request.headers.get('accept', '')

        if contenido:
            personal_obj = _obtener_o_crear_personal(request.user) if request.user.is_staff else None
            nuevo_mensaje = Mensaje(
                pedido_personalizado=pedido,
                personal=personal_obj,
                contenido=contenido,
            )
            nuevo_mensaje.anadir_mensaje()
            if propuesta:
                nuevo_mensaje.proponer_ajuste_diseno(propuesta)

            if personal_obj and not pedido.personal:
                pedido.personal = personal_obj
                pedido.save(update_fields=['personal'])

            if not es_ajax:
                messages.success(request, f"Mensaje registrado en el Pedido Personalizado #P-{pedido.id}.")
            else:
                emisor_nombre = f"{personal_obj.nombre} (Pastelería)" if personal_obj else (pedido.cliente.nombre if pedido.cliente else "Cliente")
                return JsonResponse({
                    'status': 'ok',
                    'mensaje': {
                        'id': nuevo_mensaje.id,
                        'contenido': nuevo_mensaje.contenido,
                        'propuesta_alternativa': nuevo_mensaje.propuesta_alternativa or '',
                        'es_personal': bool(personal_obj),
                        'emisor': emisor_nombre,
                        'fecha': nuevo_mensaje.fecha_envio.strftime('%d/%m %H:%M'),
                    }
                })

    if request.user.is_staff:
        return redirect('/panel-pastelero/#pills-personalizados')
    return redirect('historial_personalizados')


def obtener_mensajes_pedido(request, id):
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'error', 'message': 'No autenticado'}, status=401)

    pedido = get_object_or_404(PedidoPersonalizado, id=id)
    cliente = _obtener_o_crear_cliente(request.user) if not request.user.is_staff else None
    es_propietario = (cliente and pedido.cliente_id == cliente.id) or request.user.is_staff

    if not es_propietario:
        return JsonResponse({'status': 'error', 'message': 'Acceso no permitido'}, status=403)

    mensajes = []
    for msg in pedido.mensaje_set.all().order_by('fecha_envio'):
        if msg.personal:
            emisor = f"{msg.personal.nombre} (Pastelería)"
        else:
            emisor = pedido.cliente.nombre if pedido.cliente else "Cliente"

        mensajes.append({
            'id': msg.id,
            'contenido': msg.contenido,
            'propuesta_alternativa': msg.propuesta_alternativa or '',
            'es_personal': bool(msg.personal),
            'emisor': emisor,
            'fecha': msg.fecha_envio.strftime('%d/%m %H:%M'),
        })

    return JsonResponse({
        'status': 'ok',
        'pedido_id': pedido.id,
        'estado': pedido.estado,
        'estado_display': pedido.get_estado_display(),
        'mensajes': mensajes,
    })


def resumen_notificaciones_mensajes(request):
    if not request.user.is_authenticated:
        return JsonResponse({'status': 'error', 'message': 'No autenticado'}, status=401)

    ultimo = None
    if request.user.is_staff:
        msg = (
            Mensaje.objects
            .select_related('pedido_personalizado', 'pedido_personalizado__cliente')
            .filter(personal__isnull=True)
            .exclude(pedido_personalizado__estado__in=['Cancelado', 'Entregado'])
            .order_by('-id')
            .first()
        )
        if msg:
            cliente_nombre = msg.pedido_personalizado.cliente.nombre if msg.pedido_personalizado.cliente else "Cliente"
            ultimo = {
                'id': msg.id,
                'pedido_id': msg.pedido_personalizado_id,
                'codigo': f"P-{msg.pedido_personalizado_id:03d}",
                'emisor': cliente_nombre,
                'contenido': msg.contenido[:80] + ('...' if len(msg.contenido) > 80 else ''),
                'url': '/panel-pastelero/#pills-personalizados',
            }
    else:
        cliente = _obtener_o_crear_cliente(request.user)
        if cliente:
            msg = (
                Mensaje.objects
                .select_related('pedido_personalizado', 'personal')
                .filter(pedido_personalizado__cliente=cliente, personal__isnull=False)
                .order_by('-id')
                .first()
            )
            if msg:
                ultimo = {
                    'id': msg.id,
                    'pedido_id': msg.pedido_personalizado_id,
                    'codigo': f"P-{msg.pedido_personalizado_id:03d}",
                    'emisor': f"{msg.personal.nombre} (Pastelería)",
                    'contenido': msg.contenido[:80] + ('...' if len(msg.contenido) > 80 else ''),
                    'url': '/historial-tortas/',
                }

    boletas_estados = []
    if not request.user.is_staff:
        cliente = _obtener_o_crear_cliente(request.user)
        if cliente:
            boletas_estados = [
                {
                    'id': b.id,
                    'numero': b.numero_formateado,
                    'estado': b.estado,
                    'estado_display': b.get_estado_display(),
                    'motivo_cancelacion': b.motivo_cancelacion,
                }
                for b in Boleta.objects.filter(cliente=cliente).order_by('-id')[:20]
            ]

    return JsonResponse({
        'status': 'ok',
        'ultimo_mensaje': ultimo,
        'boletas_estados': boletas_estados,
    })


def perfil_cliente(request):
    if not request.user.is_authenticated:
        messages.warning(request, "Inicie sesión para revisar y actualizar sus datos personales.")
        return redirect('/login/?next=/mi-perfil/')
    if request.user.is_staff:
        return redirect('panel_pastelero')

    cliente = _obtener_o_crear_cliente(request.user)

    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        apellido = request.POST.get('apellido', '').strip()
        telefono = request.POST.get('telefono', '').strip()
        direccion = request.POST.get('direccion', '').strip()
        email_nuevo = request.POST.get('email', '').strip().lower()

        password_actual = request.POST.get('password_actual', '')
        password_nueva = request.POST.get('password_nueva', '')
        password_confirmar = request.POST.get('password_confirmar', '')

        if email_nuevo and email_nuevo != (request.user.email or '').lower():
            if User.objects.filter(email__iexact=email_nuevo).exclude(id=request.user.id).exists():
                messages.error(request, "El correo electrónico ingresado ya está registrado por otro usuario.")
                return redirect('perfil_cliente')
            request.user.email = email_nuevo
            cliente.email = email_nuevo

        if nombre:
            cliente.nombre = nombre[:100]
            request.user.first_name = nombre[:150]
        if apellido:
            cliente.apellido = apellido[:100]
            request.user.last_name = apellido[:150]
        if telefono:
            cliente.telefono = telefono[:15]
        if direccion:
            cliente.direccion = direccion[:200]

        cambio_password = False
        if password_actual or password_nueva or password_confirmar:
            if not request.user.check_password(password_actual):
                messages.error(request, "La contraseña actual es incorrecta.")
                return redirect('perfil_cliente')
            if len(password_nueva) < 4:
                messages.error(request, "La nueva contraseña debe tener al menos 4 caracteres.")
                return redirect('perfil_cliente')
            if password_nueva != password_confirmar:
                messages.error(request, "Las nuevas contraseñas no coinciden.")
                return redirect('perfil_cliente')
            request.user.set_password(password_nueva)
            cambio_password = True

        request.user.save()
        cliente.save()
        if cambio_password:
            update_session_auth_hash(request, request.user)
            messages.success(request, "Sus datos personales y contraseña han sido actualizados correctamente.")
        else:
            messages.success(request, "Sus datos personales y dirección predeterminada han sido actualizados.")
        return redirect('perfil_cliente')

    return render(request, 'pasteleria/perfil.html', {
        'cliente': cliente,
    })


@staff_member_required
def actualizar_estado_pedido(request, id):
    if request.method == 'POST':
        pedido = get_object_or_404(PedidoPersonalizado, id=id)
        nuevo_estado = request.POST.get('estado')
        personal_id = request.POST.get('personal_id')
        estados_validos = dict(PedidoPersonalizado.ESTADOS_PEDIDO).keys()
        es_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == '1'

        if personal_id:
            personal_asignado = Personal.objects.filter(id=personal_id).first()
            if personal_asignado:
                pedido.personal = personal_asignado
        elif not pedido.personal:
            pedido.personal = _obtener_o_crear_personal(request.user)

        if nuevo_estado in estados_validos:
            if pedido.estado == 'Entregado':
                msg = f"El pedido #{pedido.id} ya fue entregado y no puede ser modificado."
                if es_ajax:
                    return JsonResponse({'status': 'error', 'message': msg}, status=400)
                messages.warning(request, msg)
                return redirect('/panel-pastelero/#pills-personalizados')

            motivo_cancelacion = request.POST.get('motivo_cancelacion', '').strip()
            if nuevo_estado == 'Cancelado':
                if not motivo_cancelacion:
                    msg = "Debes ingresar una descripción o motivo de la cancelación para que el cliente pueda verlo."
                    if es_ajax:
                        return JsonResponse({'status': 'error', 'message': msg}, status=400)
                    messages.warning(request, msg)
                    return redirect('/panel-pastelero/#pills-personalizados')
                pedido.motivo_cancelacion = motivo_cancelacion

            pedido.estado = nuevo_estado
            pedido.save()
            msg = f"Estado del pedido #{pedido.id} actualizado a '{pedido.get_estado_display()}'."
            if not es_ajax:
                messages.success(request, msg)
            else:
                return JsonResponse({
                    'status': 'ok',
                    'nuevo_estado': nuevo_estado,
                    'nuevo_estado_display': pedido.get_estado_display(),
                    'motivo_cancelacion': pedido.motivo_cancelacion,
                    'message': msg
                })

    if es_ajax:
        return JsonResponse({'status': 'error', 'message': 'Petición inválida'}, status=400)
    return redirect('/panel-pastelero/#pills-personalizados')


# --- Vistas protegidas (Solo para el Admin / Personal) ---

@staff_member_required
def actualizar_estado_boleta(request, id):
    if request.method == 'POST':
        boleta = get_object_or_404(Boleta, id=id)
        nuevo_estado = request.POST.get('estado')
        estados_validos = dict(Boleta.ESTADOS_BOLETA).keys()
        es_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == '1'

        if boleta.estado == 'Recibida':
            msg = f"La Boleta #{boleta.id} ya fue confirmada como recibida por el cliente y no puede ser modificada."
            if es_ajax:
                return JsonResponse({'status': 'error', 'message': msg}, status=400)
            messages.warning(request, msg)
            return redirect('/panel-pastelero/#pills-boletas')

        if nuevo_estado in estados_validos:
            estado_anterior = boleta.estado
            motivo_cancelacion = request.POST.get('motivo_cancelacion', '').strip()
            if nuevo_estado == 'Cancelada':
                if not motivo_cancelacion:
                    msg = "Debes ingresar una descripción o motivo de la cancelación para que el cliente pueda verlo."
                    if es_ajax:
                        return JsonResponse({'status': 'error', 'message': msg}, status=400)
                    messages.warning(request, msg)
                    return redirect('/panel-pastelero/#pills-boletas')
                boleta.motivo_cancelacion = motivo_cancelacion

            stock_restaurado = False
            with transaction.atomic():
                if nuevo_estado == 'Cancelada' and estado_anterior != 'Cancelada':
                    for item in boleta.items.select_related('producto').all():
                        if item.producto:
                            item.producto.stock += item.cantidad
                            if item.producto.stock > 0:
                                item.producto.disponible = True
                            item.producto.save(update_fields=['stock', 'disponible'])
                            stock_restaurado = True
                boleta.estado = nuevo_estado
                boleta.save(update_fields=['estado', 'motivo_cancelacion'])

            msg = f"Estado de la Boleta #{boleta.id} actualizado a '{boleta.get_estado_display()}'."
            if stock_restaurado:
                msg += " Se restauró el stock de los productos."
            if not es_ajax:
                messages.success(request, msg)
            else:
                return JsonResponse({
                    'status': 'ok',
                    'nuevo_estado': nuevo_estado,
                    'nuevo_estado_display': boleta.get_estado_display(),
                    'motivo_cancelacion': boleta.motivo_cancelacion,
                    'message': msg
                })

    if es_ajax:
        return JsonResponse({'status': 'error', 'message': 'Petición inválida'}, status=400)
    return redirect('/panel-pastelero/#pills-boletas')


@staff_member_required
def panel_pastelero(request):
    _obtener_o_crear_personal(request.user)
    staff_rol = _obtener_rol_staff(request.user)

    pedidos_personalizados = (
        PedidoPersonalizado.objects
        .select_related('cliente', 'personal')
        .prefetch_related('mensaje_set', 'pago_set')
        .all()
        .order_by('-fecha_creacion')
    )
    boletas = Boleta.objects.prefetch_related('items').select_related('cliente').all().order_by('-fecha')
    personal_list = Personal.objects.select_related('usuario').all()

    # Vincular cada cliente registrado con su usuario web y su rol actual (si es trabajador)
    personal_por_rut = {p.rut: p for p in personal_list}
    usuarios_por_email = {u.email.lower(): u for u in User.objects.all() if u.email}
    clientes_list = []
    for c in Cliente.objects.all():
        user_asoc = usuarios_por_email.get((c.email or '').lower())
        pers_asoc = personal_por_rut.get(c.rut)
        if not pers_asoc and user_asoc:
            pers_asoc = Personal.objects.filter(usuario=user_asoc).first()
        rol_actual = 'Cliente'
        if user_asoc and user_asoc.is_staff:
            rol_actual = pers_asoc.rol if pers_asoc else ('Administrador' if user_asoc.is_superuser else 'Pastelero')
        elif pers_asoc:
            rol_actual = pers_asoc.rol
        c.usuario_asociado = user_asoc
        c.rol_actual = rol_actual
        clientes_list.append(c)

    boletas_activas = [b for b in boletas if b.estado != 'Cancelada']
    boletas_canceladas = [b for b in boletas if b.estado == 'Cancelada']
    pedidos_activos = [p for p in pedidos_personalizados if p.estado != 'Cancelado']
    pedidos_cancelados = [p for p in pedidos_personalizados if p.estado == 'Cancelado']

    total_boletas = sum(float(b.total) for b in boletas_activas)
    total_abonos = sum(float(p.monto_abono) for p in pedidos_activos)
    total_ingresos = total_boletas + total_abonos

    desglose_pagos = []
    for codigo, etiqueta in METODOS_PAGO_CHOICES:
        cant_b = sum(1 for b in boletas_activas if b.metodo_pago == codigo)
        monto_b = sum(float(b.total) for b in boletas_activas if b.metodo_pago == codigo)
        cant_p = sum(1 for p in pedidos_activos if p.metodo_pago == codigo)
        monto_p = sum(float(p.monto_abono) for p in pedidos_activos if p.metodo_pago == codigo)
        desglose_pagos.append({
            'codigo': codigo,
            'label': etiqueta,
            'cantidad': cant_b + cant_p,
            'total': round(monto_b + monto_p),
        })

    top_productos = (
        DetalleBoleta.objects
        .exclude(boleta__estado='Cancelada')
        .values('producto_nombre')
        .annotate(
            total_vendido=Sum('cantidad'),
            total_recaudado=Sum(F('cantidad') * F('precio_unitario')),
        )
        .order_by('-total_vendido')[:5]
    )

    resumen_ventas = {
        'total_boletas': round(total_boletas),
        'total_abonos': round(total_abonos),
        'total_ingresos': round(total_ingresos),
        'cant_boletas_activas': len(boletas_activas),
        'cant_boletas_canceladas': len(boletas_canceladas),
        'cant_pedidos_activos': len(pedidos_activos),
        'cant_pedidos_cancelados': len(pedidos_cancelados),
        'desglose_pagos': desglose_pagos,
        'top_productos': top_productos,
    }

    return render(request, "pasteleria/panel_pastelero.html", {
        "pedidos_personalizados": pedidos_personalizados,
        "boletas": boletas,
        "personal_list": personal_list,
        "clientes_list": clientes_list,
        "staff_rol": staff_rol,
        "resumen_ventas": resumen_ventas,
    })


@staff_member_required
def exportar_reporte_ventas(request):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="reporte_ventas_maria_bonita.csv"'
    response.write('\ufeff')

    writer = csv.writer(response)
    writer.writerow(['Tipo', 'Código', 'Fecha', 'Cliente', 'Método de Pago', 'Estado', 'Monto ($)', 'Motivo Cancelación'])

    for b in Boleta.objects.select_related('cliente').order_by('-fecha'):
        cliente_txt = f"{b.cliente.nombre} ({b.cliente.rut})" if b.cliente else "Invitado"
        writer.writerow([
            'Boleta',
            f"N° {b.numero_formateado}",
            timezone.localtime(b.fecha).strftime('%d/%m/%Y %H:%M'),
            cliente_txt,
            b.get_metodo_pago_display(),
            b.get_estado_display(),
            int(round(float(b.total))),
            b.motivo_cancelacion or '',
        ])

    for p in PedidoPersonalizado.objects.select_related('cliente').order_by('-fecha_creacion'):
        cliente_txt = f"{p.cliente.nombre} ({p.cliente.rut})" if p.cliente else "Cliente"
        writer.writerow([
            'Pedido Personalizado',
            f"P-{p.id:03d}",
            timezone.localtime(p.fecha_creacion).strftime('%d/%m/%Y %H:%M'),
            cliente_txt,
            p.get_metodo_pago_display(),
            p.get_estado_display(),
            int(round(float(p.monto_abono))),
            p.motivo_cancelacion or '',
        ])

    return response


@staff_member_required
def panel_pastelero_resumen_vivo(request):
    boletas_info = list(Boleta.objects.order_by('-id').values_list('id', 'estado', 'direccion_entrega'))
    pedidos_info = list(PedidoPersonalizado.objects.order_by('-id').values_list('id', 'estado', 'direccion_entrega'))
    ultimo_boleta_id = boletas_info[0][0] if boletas_info else 0
    ultimo_pedido_id = pedidos_info[0][0] if pedidos_info else 0
    firma = f"{len(boletas_info)}:{ultimo_boleta_id}:{hash(tuple(boletas_info))}|{len(pedidos_info)}:{ultimo_pedido_id}:{hash(tuple(pedidos_info))}"
    return JsonResponse({
        'status': 'ok',
        'boletas_count': len(boletas_info),
        'pedidos_count': len(pedidos_info),
        'ultimo_boleta_id': ultimo_boleta_id,
        'ultimo_pedido_id': ultimo_pedido_id,
        'firma': firma,
    })


def crear_resena_boleta(request, id):
    if not request.user.is_authenticated:
        return redirect(f"/login/?next=/mis-boletas/")
    if request.user.is_staff:
        return redirect('panel_pastelero')

    cliente = _obtener_o_crear_cliente(request.user)
    boleta = get_object_or_404(Boleta, id=id, cliente=cliente)

    if request.method == 'POST':
        if boleta.estado != 'Recibida':
            messages.warning(request, "Solo puede calificar una compra después de confirmar su recepción.")
            return redirect('mis_boletas')

        if Resena.objects.filter(boleta=boleta).exists():
            messages.info(request, "Ya envió una calificación para esta boleta.")
            return redirect('mis_boletas')

        try:
            calificacion = int(request.POST.get('calificacion', 5))
        except (TypeError, ValueError):
            calificacion = 5
        calificacion = max(1, min(5, calificacion))
        comentario = request.POST.get('comentario', '').strip()[:500]

        primer_item = boleta.items.select_related('producto').first()
        producto_asoc = primer_item.producto if primer_item else None

        Resena.objects.create(
            cliente=cliente,
            producto=producto_asoc,
            boleta=boleta,
            calificacion=calificacion,
            comentario=comentario,
        )
        messages.success(request, "¡Gracias por su calificación! Su reseña fue registrada.")

    return redirect('mis_boletas')


def crear_resena_pedido(request, id):
    if not request.user.is_authenticated:
        return redirect(f"/login/?next=/historial-tortas/")
    if request.user.is_staff:
        return redirect('panel_pastelero')

    cliente = _obtener_o_crear_cliente(request.user)
    pedido = get_object_or_404(PedidoPersonalizado, id=id, cliente=cliente)

    if request.method == 'POST':
        if pedido.estado != 'Entregado':
            messages.warning(request, "Solo puede calificar un pedido personalizado después de confirmar su recepción.")
            return redirect('historial_personalizados')

        if Resena.objects.filter(pedido_personalizado=pedido).exists():
            messages.info(request, "Ya envió una calificación para este pedido personalizado.")
            return redirect('historial_personalizados')

        try:
            calificacion = int(request.POST.get('calificacion', 5))
        except (TypeError, ValueError):
            calificacion = 5
        calificacion = max(1, min(5, calificacion))
        comentario = request.POST.get('comentario', '').strip()[:500]

        Resena.objects.create(
            cliente=cliente,
            pedido_personalizado=pedido,
            calificacion=calificacion,
            comentario=comentario,
        )
        messages.success(request, "¡Gracias por su calificación! Su reseña fue registrada.")

    return redirect('historial_personalizados')


@staff_member_required
def crear_personal(request):
    if _obtener_rol_staff(request.user) != 'Administrador':
        messages.error(request, "Solo el Administrador puede registrar o asignar roles de personal.")
        return redirect('panel_pastelero')

    if request.method == 'POST':
        rut = request.POST.get('rut', '').strip()
        nombre = request.POST.get('nombre', '').strip()
        telefono = request.POST.get('telefono', '').strip()
        rol = request.POST.get('rol', 'Pastelero').strip()

        if rut and nombre:
            if Personal.objects.filter(rut__iexact=rut).exists():
                messages.error(request, f"Ya existe un integrante del personal con el RUT {rut}.")
            else:
                Personal.objects.create(
                    rut=rut[:12],
                    nombre=nombre[:100],
                    telefono=(telefono or "+56900000000")[:15],
                    rol=rol,
                )
                messages.success(request, f"Se registró a {nombre} ({rol}) en el equipo de Personal.")
    return redirect('/panel-pastelero/#pills-equipo')


@staff_member_required
def asignar_rol_usuario(request, id):
    if _obtener_rol_staff(request.user) != 'Administrador':
        messages.error(request, "Solo el Administrador puede asignar roles.")
        return redirect('panel_pastelero')

    if request.method == 'POST':
        cliente = get_object_or_404(Cliente, id=id)
        nuevo_rol = request.POST.get('rol', 'Cliente').strip()
        roles_validos = ['Cliente', 'Pastelero', 'Recepcionista', 'Administrador']
        if nuevo_rol not in roles_validos:
            messages.error(request, "Rol seleccionado no válido.")
            return redirect('/panel-pastelero/#pills-equipo')

        user_obj = User.objects.filter(email__iexact=cliente.email).first()
        if not user_obj:
            messages.error(request, f"No se encontró una cuenta de usuario web asociada a {cliente.email}.")
            return redirect('/panel-pastelero/#pills-equipo')

        if user_obj.id == request.user.id and nuevo_rol != 'Administrador':
            messages.warning(request, "No puede quitarse el rol de Administrador a su propia cuenta activa.")
            return redirect('/panel-pastelero/#pills-equipo')

        if nuevo_rol == 'Cliente':
            user_obj.is_staff = False
            user_obj.is_superuser = False
            user_obj.save(update_fields=['is_staff', 'is_superuser'])
            Personal.objects.filter(usuario=user_obj).delete()
            Personal.objects.filter(rut=cliente.rut).delete()
            messages.info(request, f"{cliente.nombre} ahora tiene perfil de Cliente estándar.")
        else:
            user_obj.is_staff = True
            user_obj.is_superuser = (nuevo_rol == 'Administrador')
            user_obj.save(update_fields=['is_staff', 'is_superuser'])

            personal_obj = Personal.objects.filter(usuario=user_obj).first() or Personal.objects.filter(rut=cliente.rut).first()
            nombre_completo = f"{cliente.nombre} {cliente.apellido or ''}".strip()[:100]
            if personal_obj:
                personal_obj.nombre = nombre_completo
                personal_obj.telefono = (cliente.telefono or "+56900000000")[:15]
                personal_obj.rol = nuevo_rol
                personal_obj.usuario = user_obj
                personal_obj.save()
            else:
                Personal.objects.create(
                    rut=cliente.rut[:12],
                    nombre=nombre_completo,
                    telefono=(cliente.telefono or "+56900000000")[:15],
                    rol=nuevo_rol,
                    usuario=user_obj,
                )
            messages.success(request, f"{cliente.nombre} fue asignado como trabajador con rol: {nuevo_rol}.")

    return redirect('/panel-pastelero/#pills-equipo')


@staff_member_required
def gestion_productos(request):
    if _obtener_rol_staff(request.user) != 'Administrador':
        messages.warning(request, "La Gestión de Stock es exclusiva del Administrador.")
        return redirect('panel_pastelero')
    if request.method == 'POST':
        v_nombre = request.POST.get('nombre')
        v_descripcion = request.POST.get('descripcion')
        v_precio = request.POST.get('precio_final')
        v_stock = request.POST.get('stock')
        v_img = request.FILES.get('img')

        if v_nombre and v_precio:
            stock_int = int(v_stock) if v_stock else 0
            Producto.objects.create(
                nombre=v_nombre,
                descripcion=v_descripcion,
                precio_final=v_precio,
                stock=stock_int,
                disponible=stock_int > 0,
                img=v_img
            )
            messages.success(request, f"Producto '{v_nombre}' creado correctamente.")
        return redirect('gestion_productos')

    productos = Producto.objects.all()
    return render(request, "pasteleria/gestion_productos.html", {"productos": productos})


# --- Vistas de autenticación y registro ---

def iniciar_sesion(request):
    next_url = request.GET.get('next') or request.POST.get('next') or ''

    if request.method == 'POST':
        identificador = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')

        user = authenticate(request, username=identificador, password=password)
        if user is None and '@' in identificador:
            user_por_email = User.objects.filter(email__iexact=identificador).first()
            if user_por_email:
                user = authenticate(request, username=user_por_email.username, password=password)

        if user is not None:
            carrito_previo = request.session.get('carrito', {})
            login(request, user)
            if carrito_previo:
                request.session['carrito'] = carrito_previo
                request.session.modified = True

            if not user.is_staff:
                _obtener_o_crear_cliente(user)

            messages.success(request, f"Bienvenido/a, {user.first_name or user.username}.")

            if next_url and next_url.startswith('/'):
                return redirect(next_url)
            if user.is_staff:
                return redirect('panel_pastelero')
            return redirect('catalogo')
        else:
            messages.error(request, "Usuario o contraseña incorrectos. Verifique sus datos o cree una cuenta nueva.")

    return render(request, 'pasteleria/login.html', {'next': next_url})


def registrar_usuario(request):
    next_url = request.GET.get('next') or request.POST.get('next') or ''
    valores = {}

    if request.method == 'POST':
        username_raw = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip().lower()
        nombre = request.POST.get('nombre', '').strip()
        apellido = request.POST.get('apellido', '').strip()
        rut = request.POST.get('rut', '').strip()
        telefono = request.POST.get('telefono', '').strip()
        direccion = request.POST.get('direccion', '').strip()
        password1 = request.POST.get('password1', '')
        password2 = request.POST.get('password2', '')

        valores = {
            'username': username_raw,
            'email': email,
            'nombre': nombre,
            'apellido': apellido,
            'rut': rut,
            'telefono': telefono,
            'direccion': direccion,
        }

        errores = []
        if not username_raw:
            errores.append("Debe ingresar un nombre de usuario.")
        elif User.objects.filter(username__iexact=username_raw).exists():
            errores.append(f"El nombre de usuario '{username_raw}' ya está registrado.")

        if not email:
            errores.append("Debe ingresar un correo electrónico válido.")
        elif User.objects.filter(email__iexact=email).exists() or Cliente.objects.filter(email__iexact=email).exists():
            errores.append(f"El correo '{email}' ya se encuentra registrado.")

        if rut and Cliente.objects.filter(rut__iexact=rut).exists():
            errores.append(f"El RUT '{rut}' ya se encuentra registrado.")

        if not password1 or len(password1) < 4:
            errores.append("La contraseña debe tener al menos 4 caracteres.")
        elif password1 != password2:
            errores.append("Las contraseñas ingresadas no coinciden.")

        if not errores:
            carrito_previo = request.session.get('carrito', {})

            user = User.objects.create_user(
                username=username_raw,
                email=email,
                password=password1,
                first_name=nombre or username_raw,
                last_name=apellido,
            )

            _obtener_o_crear_cliente(
                user,
                rut=rut,
                nombre=nombre or username_raw,
                apellido=apellido,
                telefono=telefono,
                direccion=direccion,
            )

            login(request, user)
            if carrito_previo:
                request.session['carrito'] = carrito_previo
                request.session.modified = True

            messages.success(request, f"Cuenta creada correctamente. Bienvenido/a, {user.first_name or user.username}.")

            if next_url and next_url.startswith('/'):
                return redirect(next_url)
            return redirect('catalogo')
        else:
            for err in errores:
                messages.error(request, err)

    return render(request, 'pasteleria/registro.html', {
        'valores': valores,
        'next': next_url,
    })


def cerrar_sesion(request):
    logout(request)
    messages.info(request, "Ha cerrado su sesión correctamente.")
    return redirect('login')


# --- Acciones sobre productos (Protegidas para Staff) ---

@staff_member_required
def renovar_stock(request, id):
    if request.method == 'POST':
        producto = get_object_or_404(Producto, id=id)
        producto.stock = 5
        producto.disponible = True
        producto.save()
        messages.success(request, f"Stock de '{producto.nombre}' renovado a 5 unidades.")
    return redirect('gestion_productos')


@staff_member_required
def eliminar_producto(request, id):
    if request.method == 'POST':
        producto = get_object_or_404(Producto, id=id)
        nombre = producto.nombre
        producto.delete()
        messages.info(request, f"Producto '{nombre}' eliminado.")
    return redirect('gestion_productos')


@staff_member_required
def editar_producto(request, id):
    producto = get_object_or_404(Producto, id=id)

    if request.method == 'POST':
        producto.nombre = request.POST.get('nombre')
        producto.descripcion = request.POST.get('descripcion')
        producto.precio_final = request.POST.get('precio_final')
        stock_int = int(request.POST.get('stock', 0))
        producto.stock = stock_int
        producto.disponible = stock_int > 0

        if request.FILES.get('img'):
            producto.img = request.FILES.get('img')

        producto.save()
        messages.success(request, f"Producto '{producto.nombre}' actualizado.")
        return redirect('gestion_productos')

    return render(request, 'pasteleria/editar_producto.html', {'producto': producto})


# --- Vistas del Carrito y Boletas ---

def ver_carrito(request):
    if request.user.is_authenticated and request.user.is_staff:
        return redirect('panel_pastelero')

    carrito = request.session.get('carrito', {})
    productos_carrito = []
    total_carrito = 0
    ids_obsoletos = []

    for producto_id, cantidad in carrito.items():
        producto = Producto.objects.filter(id=producto_id).first()
        if not producto:
            ids_obsoletos.append(producto_id)
            continue
        subtotal = producto.precio_final * cantidad
        total_carrito += subtotal
        productos_carrito.append({
            'producto': producto,
            'cantidad': cantidad,
            'subtotal': subtotal
        })

    if ids_obsoletos:
        for pid in ids_obsoletos:
            carrito.pop(pid, None)
        request.session['carrito'] = carrito

    boletas_recientes = Boleta.objects.none()
    if request.user.is_authenticated:
        cliente = _obtener_o_crear_cliente(request.user)
        boletas_recientes = Boleta.objects.prefetch_related('items').filter(cliente=cliente).order_by('-fecha')

    return render(request, 'pasteleria/carrito.html', {
        'productos_carrito': productos_carrito,
        'total_carrito': total_carrito,
        'boletas_recientes': boletas_recientes,
    })


def agregar_al_carrito(request, id):
    if request.user.is_authenticated and request.user.is_staff:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'status': 'error', 'message': 'El administrador no utiliza carrito'}, status=403)
        return redirect('panel_pastelero')

    producto = get_object_or_404(Producto, id=id)
    carrito = request.session.get('carrito', {})

    cantidad_actual = carrito.get(str(id), 0)
    es_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == '1'

    if producto.verificar_disponibilidad() and producto.stock > cantidad_actual:
        nueva_cantidad = cantidad_actual + 1
        carrito[str(id)] = nueva_cantidad
        request.session['carrito'] = carrito
        request.session.modified = True
        total_items = sum(int(c) for c in carrito.values())
        subtotal_item = float(producto.precio_final * nueva_cantidad)
        total_carrito = sum(float(Producto.objects.get(id=int(pid)).precio_final * cant) for pid, cant in carrito.items() if Producto.objects.filter(id=int(pid)).exists())

        if es_ajax:
            return JsonResponse({
                'status': 'ok',
                'message': f"Se añadió '{producto.nombre}' a su carrito de compras.",
                'item_id': id,
                'cantidad': nueva_cantidad,
                'subtotal': subtotal_item,
                'total_carrito': total_carrito,
                'total_items': total_items,
            })
        messages.success(request, f"Se añadió '{producto.nombre}' a su carrito de compras.")
    else:
        msg = f"No hay más stock disponible de '{producto.nombre}' (máximo {producto.stock})."
        if es_ajax:
            return JsonResponse({'status': 'error', 'message': msg}, status=400)
        messages.error(request, msg)

    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url == 'carrito':
        return redirect('ver_carrito')
    return redirect('catalogo')


def restar_del_carrito(request, id):
    carrito = request.session.get('carrito', {})
    key = str(id)
    es_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == '1'

    nueva_cantidad = 0
    if key in carrito:
        if carrito[key] > 1:
            carrito[key] -= 1
            nueva_cantidad = carrito[key]
        else:
            del carrito[key]
            nueva_cantidad = 0
        request.session['carrito'] = carrito
        request.session.modified = True

    if es_ajax:
        producto = Producto.objects.filter(id=id).first()
        subtotal_item = float(producto.precio_final * nueva_cantidad) if (producto and nueva_cantidad > 0) else 0.0
        total_items = sum(int(c) for c in carrito.values())
        total_carrito = sum(float(Producto.objects.get(id=int(pid)).precio_final * cant) for pid, cant in carrito.items() if Producto.objects.filter(id=int(pid)).exists())
        return JsonResponse({
            'status': 'ok',
            'item_id': id,
            'cantidad': nueva_cantidad,
            'subtotal': subtotal_item,
            'total_carrito': total_carrito,
            'total_items': total_items,
        })

    return redirect('ver_carrito')


def eliminar_del_carrito(request, id):
    carrito = request.session.get('carrito', {})
    key = str(id)
    es_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == '1'

    if key in carrito:
        producto = Producto.objects.filter(id=id).first()
        del carrito[key]
        request.session['carrito'] = carrito
        request.session.modified = True
        if not es_ajax and producto:
            messages.info(request, f"Se quitó '{producto.nombre}' del carrito.")

    if es_ajax:
        total_items = sum(int(c) for c in carrito.values())
        total_carrito = sum(float(Producto.objects.get(id=int(pid)).precio_final * cant) for pid, cant in carrito.items() if Producto.objects.filter(id=int(pid)).exists())
        return JsonResponse({
            'status': 'ok',
            'item_id': id,
            'cantidad': 0,
            'total_carrito': total_carrito,
            'total_items': total_items,
        })

    return redirect('ver_carrito')


def vaciar_carrito(request):
    if request.method == 'POST':
        request.session['carrito'] = {}
        request.session.modified = True
        messages.info(request, "Se ha vaciado su carrito de compras.")
    return redirect('ver_carrito')


def procesar_compra(request):
    es_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == '1'

    if not request.user.is_authenticated:
        if es_ajax:
            return JsonResponse({'status': 'error', 'message': 'Debe iniciar sesión para confirmar su compra.'}, status=401)
        messages.warning(
            request,
            "Para confirmar su compra debe iniciar sesión o crear una cuenta. Sus productos siguen guardados en el carrito."
        )
        return redirect('/login/?next=/carrito/')
    if request.user.is_staff:
        if es_ajax:
            return JsonResponse({'status': 'error', 'message': 'El personal no realiza compras.'}, status=403)
        return redirect('panel_pastelero')

    carrito = request.session.get('carrito', {})
    if not carrito:
        if es_ajax:
            return JsonResponse({'status': 'error', 'message': 'Su carrito está vacío.'}, status=400)
        messages.error(request, "Su carrito está vacío.")
        return redirect('ver_carrito')

    total = 0
    items_a_comprar = []

    for producto_id, cantidad in carrito.items():
        producto = get_object_or_404(Producto, id=producto_id)
        if not producto.verificar_disponibilidad() or producto.stock < cantidad:
            msg = f"Stock insuficiente para {producto.nombre} (disponibles: {producto.stock})."
            if es_ajax:
                return JsonResponse({'status': 'error', 'message': msg}, status=400)
            messages.error(request, msg)
            return redirect('ver_carrito')

        subtotal = producto.precio_final * cantidad
        total += subtotal
        items_a_comprar.append((producto, cantidad, subtotal))

    cliente = _obtener_o_crear_cliente(request.user)

    tipos_entrega_validos = dict(TIPOS_ENTREGA_CHOICES).keys()
    tipo_entrega = request.POST.get('tipo_entrega', 'Domicilio').strip()
    if tipo_entrega not in tipos_entrega_validos:
        tipo_entrega = 'Domicilio'
    costo_envio = COSTO_DESPACHO_DOMICILIO if tipo_entrega == 'Domicilio' else 0
    total += costo_envio

    if tipo_entrega == 'Retiro':
        direccion_boleta = "Retiro en Local"
    else:
        # Toma automáticamente la dirección que ingresó al registrarse el usuario
        direccion_boleta = (cliente.direccion or "").strip()
        if not direccion_boleta or direccion_boleta.lower() == "por confirmar":
            direccion_boleta = "Por confirmar"

    metodos_validos = dict(METODOS_PAGO_CHOICES).keys()
    metodo_pago = request.POST.get('metodo_pago', 'Debito').strip()
    if metodo_pago not in metodos_validos:
        metodo_pago = 'Debito'

    boleta = Boleta.objects.create(
        cliente=cliente,
        tipo_entrega=tipo_entrega,
        costo_envio=costo_envio,
        direccion_entrega=direccion_boleta,
        metodo_pago=metodo_pago,
        total=total
    )

    for producto, cantidad, subtotal in items_a_comprar:
        producto.stock -= cantidad
        producto.disponible = producto.stock > 0
        producto.save()

        DetalleBoleta.objects.create(
            boleta=boleta,
            producto=producto,
            producto_nombre=producto.nombre,
            cantidad=cantidad,
            precio_unitario=producto.precio_final
        )

    request.session['carrito'] = {}
    request.session.modified = True

    if es_ajax:
        return JsonResponse({
            'status': 'ok',
            'boleta_id': boleta.id,
            'numero_boleta': boleta.numero_formateado,
            'metodo_pago': boleta.get_metodo_pago_display(),
            'total': float(boleta.total),
            'url_mis_boletas': '/mis-boletas/',
            'url_descargar_pdf': f'/boleta/descargar/{boleta.id}/',
        })

    messages.success(request, f"Compra realizada con éxito. Se ha generado la Boleta N° {boleta.numero_formateado}.")
    return redirect('ver_carrito')


def mis_boletas(request):
    if not request.user.is_authenticated:
        messages.warning(request, "Inicie sesión para revisar el historial de sus boletas.")
        return redirect('/login/?next=/mis-boletas/')
    if request.user.is_staff:
        return redirect('panel_pastelero')

    cliente = _obtener_o_crear_cliente(request.user)
    boletas = Boleta.objects.prefetch_related('items').filter(cliente=cliente).order_by('-fecha')
    return render(request, 'pasteleria/mis_boletas.html', {
        'boletas': boletas,
    })


def editar_direccion_boleta(request, id):
    if not request.user.is_authenticated:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == '1':
            return JsonResponse({'status': 'error', 'message': 'No autenticado'}, status=401)
        return redirect('login')

    es_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == '1'

    if request.method == 'POST':
        boleta = get_object_or_404(Boleta, id=id)
        cliente = _obtener_o_crear_cliente(request.user) if not request.user.is_staff else None
        es_propietario = (cliente and boleta.cliente_id == cliente.id) or request.user.is_staff

        if es_propietario:
            if boleta.estado in ['En_Revision', 'En_Preparacion']:
                nueva_dir = request.POST.get('direccion_entrega', '').strip()
                if nueva_dir:
                    boleta.direccion_entrega = nueva_dir[:200]
                    boleta.save(update_fields=['direccion_entrega'])
                    if cliente and (not cliente.direccion or cliente.direccion == "Por confirmar"):
                        cliente.direccion = nueva_dir[:200]
                        cliente.save(update_fields=['direccion'])
                    if es_ajax:
                        return JsonResponse({'status': 'ok', 'direccion_entrega': boleta.direccion_entrega})
                    messages.success(request, f"Dirección de entrega actualizada correctamente para la Boleta N° {boleta.numero_formateado}.")
                else:
                    if es_ajax:
                        return JsonResponse({'status': 'error', 'message': 'La dirección no puede estar vacía'}, status=400)
                    messages.error(request, "La dirección de entrega no puede estar vacía.")
            else:
                if es_ajax:
                    return JsonResponse({'status': 'error', 'message': 'La dirección ya no puede ser modificada'}, status=400)
                messages.warning(request, "La dirección ya no puede ser modificada porque el pedido se encuentra en camino o finalizado.")

    if request.user.is_staff:
        return redirect('/panel-pastelero/#pills-boletas')
    return redirect('mis_boletas')


def editar_direccion_pedido_personalizado(request, id):
    if not request.user.is_authenticated:
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == '1':
            return JsonResponse({'status': 'error', 'message': 'No autenticado'}, status=401)
        return redirect('login')

    es_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == '1'

    if request.method == 'POST':
        pedido = get_object_or_404(PedidoPersonalizado, id=id)
        cliente = _obtener_o_crear_cliente(request.user) if not request.user.is_staff else None
        es_propietario = (cliente and pedido.cliente_id == cliente.id) or request.user.is_staff

        if es_propietario:
            if pedido.estado in ['Pendiente_Coordinacion', 'Aprobado_En_Produccion']:
                nueva_dir = request.POST.get('direccion_entrega', '').strip()
                if nueva_dir:
                    pedido.direccion_entrega = nueva_dir[:200]
                    pedido.save(update_fields=['direccion_entrega'])
                    if cliente and (not cliente.direccion or cliente.direccion == "Por confirmar"):
                        cliente.direccion = nueva_dir[:200]
                        cliente.save(update_fields=['direccion'])
                    if es_ajax:
                        return JsonResponse({'status': 'ok', 'direccion_entrega': pedido.direccion_entrega})
                    messages.success(request, f"Dirección de entrega actualizada correctamente para la Torta P-{pedido.id:03d}.")
                else:
                    if es_ajax:
                        return JsonResponse({'status': 'error', 'message': 'La dirección no puede estar vacía'}, status=400)
                    messages.error(request, "La dirección de entrega no puede estar vacía.")
            else:
                if es_ajax:
                    return JsonResponse({'status': 'error', 'message': 'La dirección ya no puede ser modificada'}, status=400)
                messages.warning(request, "La dirección ya no puede ser modificada porque el pedido ya está listo o en camino.")

    if request.user.is_staff:
        return redirect('/panel-pastelero/#pills-personalizados')
    return redirect('historial_personalizados')


def confirmar_boleta_recibida(request, id):
    if not request.user.is_authenticated:
        return redirect('login')

    if request.method == 'POST':
        boleta = get_object_or_404(Boleta, id=id)
        cliente = _obtener_o_crear_cliente(request.user)
        es_propietario = (cliente and boleta.cliente_id == cliente.id) or request.user.is_staff

        if es_propietario:
            if boleta.estado == 'En_Camino':
                boleta.estado = 'Recibida'
                boleta.save(update_fields=['estado'])
                messages.success(request, f"¡Gracias! Ha confirmado la recepción de su compra (Boleta #{boleta.id}).")
            elif boleta.estado == 'Recibida':
                messages.info(request, "Esta compra ya fue confirmada como recibida previamente.")
            else:
                messages.warning(request, "Solo puede confirmar recepción cuando el pedido esté listo y en camino a su domicilio.")

    return redirect('mis_boletas')


def comprar_producto(request, id):
    if request.method == 'POST':
        producto = get_object_or_404(Producto, id=id)
        carrito = request.session.get('carrito', {})
        cantidad_actual = carrito.get(str(id), 0)
        if producto.verificar_disponibilidad() and producto.stock > cantidad_actual:
            carrito[str(id)] = cantidad_actual + 1
            request.session['carrito'] = carrito
            request.session.modified = True
            messages.success(request, f"'{producto.nombre}' se guardó en su carrito de compras.")
        else:
            messages.error(request, f"No hay más stock disponible para '{producto.nombre}'.")

        ir_a_carrito = request.POST.get('ir_carrito')
        if ir_a_carrito:
            return redirect('ver_carrito')

    respuesta = redirect('catalogo')
    respuesta['Location'] += '#productos'
    return respuesta


def _formato_clp(valor):
    return f"${round(float(valor or 0)):,}".replace(",", ".")


def descargar_boleta(request, id):
    if not request.user.is_authenticated:
        return redirect('login')

    boleta = get_object_or_404(Boleta.objects.prefetch_related('items').select_related('cliente'), id=id)
    cliente = _obtener_o_crear_cliente(request.user) if not request.user.is_staff else None
    es_propietario = (cliente and boleta.cliente_id == cliente.id) or request.user.is_staff

    if not es_propietario:
        messages.error(request, "No tiene permisos para descargar esta boleta.")
        return redirect('mis_boletas')

    if boleta.estado == 'Cancelada':
        messages.warning(request, "No es posible descargar una boleta cancelada.")
        return redirect('mis_boletas')

    cli = boleta.cliente
    nombre_cli = f"{cli.nombre} {cli.apellido}".strip() if cli else "Cliente General"
    datos_cliente = [
        ("Cliente", nombre_cli),
        ("RUT", cli.rut if cli else "-"),
        ("Telefono", cli.telefono if cli else "-"),
        ("Direccion Entrega", boleta.direccion_entrega or "Por confirmar"),
        ("Tipo de Compra / Pago", boleta.get_metodo_pago_display()),
        ("Fecha Emision", timezone.localtime(boleta.fecha).strftime("%d/%m/%Y %H:%M")),
        ("Estado", boleta.get_estado_display()),
    ]

    filas = []
    for item in boleta.items.all():
        filas.append((
            item.producto_nombre,
            item.cantidad,
            _formato_clp(item.precio_unitario),
            _formato_clp(item.cantidad * item.precio_unitario),
        ))

    resumen = [
        ("TOTAL PAGADO:", _formato_clp(boleta.total), True),
    ]

    pdf_bytes = construir_pdf_boleta(
        titulo=f"BOLETA DE COMPRA N. {boleta.numero_formateado}",
        subtitulo=f"Fecha: {timezone.localtime(boleta.fecha).strftime('%d/%m/%Y')}",
        datos_cliente=datos_cliente,
        filas_detalle=filas,
        resumen_montos=resumen,
    )

    resp = HttpResponse(pdf_bytes, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="Boleta_{boleta.numero_formateado}.pdf"'
    return resp


def descargar_boleta_personalizada(request, id):
    if not request.user.is_authenticated:
        return redirect('login')

    pedido = get_object_or_404(PedidoPersonalizado.objects.select_related('cliente', 'personal'), id=id)
    cliente = _obtener_o_crear_cliente(request.user) if not request.user.is_staff else None
    es_propietario = (cliente and pedido.cliente_id == cliente.id) or request.user.is_staff

    if not es_propietario:
        messages.error(request, "No tiene permisos para descargar esta boleta.")
        return redirect('historial_personalizados')

    if pedido.estado == 'Cancelado':
        messages.warning(request, "No es posible descargar una boleta de un pedido cancelado.")
        return redirect('historial_personalizados')

    cli = pedido.cliente
    nombre_cli = f"{cli.nombre} {cli.apellido}".strip() if cli else "Cliente"
    datos_cliente = [
        ("Cliente", nombre_cli),
        ("RUT", cli.rut if cli else "-"),
        ("Telefono", cli.telefono if cli else "-"),
        ("Direccion Entrega", pedido.direccion_entrega or "Por confirmar"),
        ("Tipo de Pago (Abono)", pedido.get_metodo_pago_display()),
        ("Fecha Solicitud", timezone.localtime(pedido.fecha_creacion).strftime("%d/%m/%Y %H:%M")),
        ("Fecha Entrega", timezone.localtime(pedido.fecha_entrega).strftime("%d/%m/%Y %H:%M")),
        ("Estado", pedido.get_estado_display()),
    ]

    filas = [
        (
            f"Torta Personalizada ({pedido.tipo_bizcocho} / {pedido.rellenos} / {pedido.coberturas})",
            1,
            _formato_clp(pedido.precio_total),
            _formato_clp(pedido.precio_total),
        )
    ]
    if pedido.notas_decoracion:
        filas.append((f"Notas: {pedido.notas_decoracion}", "-", "-", "-"))

    resumen = [
        ("Total Estimado:", _formato_clp(pedido.precio_total), False),
        ("Abono Pagado (25%):", _formato_clp(pedido.monto_abono), True),
        ("Saldo Pendiente (75%):", _formato_clp(pedido.saldo_pendiente), False),
    ]

    pdf_bytes = construir_pdf_boleta(
        titulo=f"BOLETA TORTA PERSONALIZADA P-{pedido.id:03d}",
        subtitulo=f"Entrega: {timezone.localtime(pedido.fecha_entrega).strftime('%d/%m/%Y')}",
        datos_cliente=datos_cliente,
        filas_detalle=filas,
        resumen_montos=resumen,
    )

    resp = HttpResponse(pdf_bytes, content_type='application/pdf')
    resp['Content-Disposition'] = f'attachment; filename="Boleta_Personalizada_P-{pedido.id:03d}.pdf"'
    return resp
