from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from .models import Producto, Boleta, DetalleBoleta
from django.shortcuts import render, redirect, get_object_or_404
from .models import Producto

# --- Vistas públicas ---

def catalogo(request):
    productos = Producto.objects.all()
    return render(request, "pasteleria/catalogo.html", {"productos": productos})

def detalle_producto(request, id):
    producto = get_object_or_404(Producto, id=id)
    return render(request, "pasteleria/detalle_producto.html", {"producto": producto})

def pedido_personalizado(request):
    return render(request, "pasteleria/pedido_personalizado.html")


# --- Vistas protegidas (Solo para el Admin / Personal) ---

@staff_member_required
def panel_pastelero(request):
    return render(request, "pasteleria/panel_pastelero.html")

@staff_member_required
def gestion_productos(request):
    if request.method == 'POST':
        v_nombre = request.POST.get('nombre')
        v_descripcion = request.POST.get('descripcion')
        v_precio = request.POST.get('precio_final') 
        v_stock = request.POST.get('stock')
        v_img = request.FILES.get('img')
        
        if v_nombre and v_precio:
            Producto.objects.create(
                nombre=v_nombre,
                descripcion=v_descripcion,
                precio_final=v_precio,
                stock=v_stock,
                img=v_img
            )
        return redirect('gestion_productos')
        
    productos = Producto.objects.all()
    return render(request, "pasteleria/gestion_productos.html", {"productos": productos})


# --- Vistas de autenticación con redirección por roles ---

def iniciar_sesion(request):
    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            messages.success(request, f"¡Bienvenido/a {user.username}!")
            
            if user.is_staff:
                return redirect('panel_pastelero')
            else:
                return redirect('catalogo')
        else:
            messages.error(request, "Usuario o contraseña incorrectos.")
    else:
        form = AuthenticationForm()
    return render(request, 'pasteleria/login.html', {'form': form})

def registrar_usuario(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Cuenta creada exitosamente.")
            return redirect('catalogo')
    else:
        form = UserCreationForm()
    return render(request, 'pasteleria/registro.html', {'form': form})

def cerrar_sesion(request):
    logout(request)
    return redirect('login')


# --- Acciones sobre productos (Protegidas para Staff) ---

@staff_member_required
def renovar_stock(request, id):
    if request.method == 'POST':
        producto = get_object_or_404(Producto, id=id)
        producto.stock = 5
        producto.save()
    return redirect('gestion_productos')

@staff_member_required
def eliminar_producto(request, id):
    if request.method == 'POST':
        producto = get_object_or_404(Producto, id=id)
        producto.delete()
    return redirect('gestion_productos')

@staff_member_required
def editar_producto(request, id):
    producto = get_object_or_404(Producto, id=id)
    
    if request.method == 'POST':
        producto.nombre = request.POST.get('nombre')
        producto.descripcion = request.POST.get('descripcion')
        producto.precio_final = request.POST.get('precio_final')
        producto.stock = request.POST.get('stock')
        
        if request.FILES.get('img'):
            producto.img = request.FILES.get('img')
            
        producto.save()
        return redirect('gestion_productos')
        
    return render(request, 'pasteleria/editar_producto.html', {'producto': producto})


# --- Vistas del Carrito y Boletas (Exclusivas para Clientes / No Staff) ---

@login_required
def ver_carrito(request):
    if request.user.is_staff:
        return redirect('panel_pastelero')
        
    carrito = request.session.get('carrito', {})
    productos_carrito = []
    total_carrito = 0

    for producto_id, cantidad in carrito.items():
        producto = get_object_or_404(Producto, id=producto_id)
        subtotal = producto.precio_final * cantidad
        total_carrito += subtotal
        productos_carrito.append({
            'producto': producto,
            'cantidad': cantidad,
            'subtotal': subtotal
        })

    return render(request, 'pasteleria/carrito.html', {
        'productos_carrito': productos_carrito,
        'total_carrito': total_carrito
    })

@login_required
def agregar_al_carrito(request, id):
    if request.user.is_staff:
        return redirect('catalogo')
        
    producto = get_object_or_404(Producto, id=id)
    carrito = request.session.get('carrito', {})

    cantidad_actual = carrito.get(str(id), 0)
    if producto.stock > cantidad_actual:
        carrito[str(id)] = cantidad_actual + 1
        request.session['carrito'] = carrito
        messages.success(request, f"Se añadió {producto.nombre} al carrito.")
    else:
        messages.error(request, "No hay suficiente stock disponible.")

    return redirect('catalogo')

@login_required
def procesar_compra(request):
    if request.user.is_staff:
        return redirect('catalogo')
        
    carrito = request.session.get('carrito', {})
    if not carrito:
        messages.error(request, "Tu carrito está vacío.")
        return redirect('ver_carrito')

    total = 0
    items_a_comprar = []

    for producto_id, cantidad in carrito.items():
        producto = get_object_or_404(Producto, id=producto_id)
        if producto.stock < cantidad:
            messages.error(request, f"Lo sentimos, stock insuficiente para {producto.nombre}.")
            return redirect('ver_carrito')
        
        subtotal = producto.precio_final * cantidad
        total += subtotal
        items_a_comprar.append((producto, cantidad, subtotal))

    boleta = Boleta.objects.create(usuario=request.user, total=total)

    for producto, cantidad, subtotal in items_a_comprar:
        DetalleBoleta.objects.create(
            boleta=boleta,
            producto_nombre=producto.nombre,
            cantidad=cantidad,
            precio_unitario=producto.precio_final
        )
        producto.stock -= cantidad
        producto.save()

    request.session['carrito'] = {}
    messages.success(request, f"¡Compra realizada con éxito! Se ha generado tu Boleta #{boleta.id}.")
    return redirect('mis_boletas')

@login_required
def mis_boletas(request):
    if request.user.is_staff:
        return redirect('panel_pastelero')
        
    boletas = Boleta.objects.filter(usuario=request.user).order_by('-fecha')
    return render(request, 'pasteleria/mis_boletas.html', {'boletas': boletas})

def comprar_producto(request, id):
    if request.method == 'POST':
        producto = get_object_or_404(Producto, id=id)
        if producto.stock > 0:
            producto.stock -= 1  # Resta 1 al stock actual
            producto.save()      # Guarda el cambio en la base de datos
            
    # Redirecciona al catálogo y baja automáticamente a la sección de productos
    respuesta = redirect('catalogo')
    respuesta['Location'] += '#productos'
    return respuesta