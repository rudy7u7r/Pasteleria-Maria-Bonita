/*
 * Interfaz Pastelería María Bonita
 * 1) Paginación reutilizable: agregar data-paginar="N" a cualquier contenedor (tbody, .row, etc.).
 *    - Cada hijo directo es un elemento de la lista.
 *    - Respeta los filtros existentes: los elementos con la clase "d-none" se consideran filtrados.
 *    - Se actualiza sola cuando el contenido cambia (filtros, refresco en vivo del panel, orden del catálogo).
 * 2) Animaciones: aparición suave de tarjetas al hacer scroll y botón "volver arriba".
 */
(function () {
  'use strict';

  const reducirMovimiento = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ===================== PAGINACIÓN =====================
  function crearPaginador(contenedor) {
    const porPagina = Math.max(1, parseInt(contenedor.dataset.paginar, 10) || 10);
    const etiqueta = contenedor.dataset.paginarEtiqueta || 'elementos';
    let paginaActual = 1;
    let firmaFiltro = null;
    let programado = false;

    // Los controles van debajo de la tabla (si es un tbody) o del propio contenedor
    const ancla = contenedor.tagName === 'TBODY'
      ? (contenedor.closest('.table-responsive') || contenedor.closest('table'))
      : contenedor;
    const nav = document.createElement('nav');
    nav.className = 'paginador';
    nav.setAttribute('aria-label', 'Paginación de ' + etiqueta);
    ancla.insertAdjacentElement('afterend', nav);

    const itemsVisibles = () => Array.from(contenedor.children).filter(el =>
      !el.classList.contains('d-none') && !el.hasAttribute('data-no-paginar'));

    // Firma de "qué se ve y en qué orden": cambia con filtros u ordenamiento, no con cambios de estado
    function firmaActual() {
      return Array.from(contenedor.children)
        .map(el => (el.classList.contains('d-none') ? '0' : '1') + (el.dataset.nombre || ''))
        .join('|');
    }

    function render(animar) {
      const items = itemsVisibles();
      const total = items.length;
      const paginas = Math.max(1, Math.ceil(total / porPagina));
      paginaActual = Math.min(Math.max(1, paginaActual), paginas);
      const inicio = (paginaActual - 1) * porPagina;
      const fin = inicio + porPagina;

      Array.from(contenedor.children).forEach(el => {
        el.classList.remove('pag-oculto');
        el.dataset.pag = '1'; // marca: este elemento ya fue paginado
      });
      items.forEach((el, i) => {
        const fuera = i < inicio || i >= fin;
        el.classList.toggle('pag-oculto', fuera);
        if (!fuera && animar && !reducirMovimiento) {
          el.classList.remove('pag-entrada');
          void el.offsetWidth; // reinicia la animación
          el.style.animationDelay = Math.min((i - inicio) * 35, 280) + 'ms';
          el.classList.add('pag-entrada');
        }
      });

      if (total <= porPagina) {
        nav.innerHTML = '';
        nav.hidden = true;
        return;
      }
      nav.hidden = false;
      nav.innerHTML = construirControles(paginas, inicio + 1, Math.min(fin, total), total);
    }

    function construirControles(paginas, desde, hasta, total) {
      const boton = (num, texto, extra, deshabilitado, aria) =>
        `<li class="page-item ${extra || ''} ${deshabilitado ? 'disabled' : ''}">
           <button type="button" class="page-link" data-pagina="${num}" ${deshabilitado ? 'disabled tabindex="-1"' : ''}
             ${aria ? `aria-label="${aria}"` : ''} ${extra === 'active' ? 'aria-current="page"' : ''}>${texto}</button>
         </li>`;
      // Números con "…" cuando hay muchas páginas: 1 … 4 5 6 … 12
      const numeros = [];
      for (let p = 1; p <= paginas; p++) {
        if (p === 1 || p === paginas || Math.abs(p - paginaActual) <= 1) numeros.push(p);
        else if (numeros[numeros.length - 1] !== '…') numeros.push('…');
      }
      const items = numeros.map(p => p === '…'
        ? '<li class="page-item disabled"><span class="page-link">…</span></li>'
        : boton(p, p, p === paginaActual ? 'active' : '', false, 'Página ' + p)).join('');
      return `<span class="paginador-info">Mostrando ${desde}–${hasta} de ${total} ${etiqueta}</span>
        <ul class="pagination pagination-sm mb-0">
          ${boton(paginaActual - 1, '&lsaquo; Anterior', 'pag-extremo', paginaActual === 1, 'Página anterior')}
          ${items}
          ${boton(paginaActual + 1, 'Siguiente &rsaquo;', 'pag-extremo', paginaActual === paginas, 'Página siguiente')}
        </ul>`;
    }

    nav.addEventListener('click', e => {
      const btn = e.target.closest('[data-pagina]');
      if (!btn || btn.disabled) return;
      paginaActual = parseInt(btn.dataset.pagina, 10);
      render(true);
      // Si el inicio de la lista quedó fuera de pantalla, volver a él
      const arriba = (contenedor.closest('.card') || ancla).getBoundingClientRect().top;
      if (arriba < 70) {
        window.scrollBy({ top: arriba - 90, behavior: reducirMovimiento ? 'auto' : 'smooth' });
      }
    });

    function revisarCambios() {
      programado = false;
      const firma = firmaActual();
      const hayNuevos = Array.from(contenedor.children).some(el => el.dataset.pag !== '1');
      if (firma === firmaFiltro && !hayNuevos) return; // nada relevante cambió (evita bucles)
      const cambioFiltro = firma !== firmaFiltro;
      if (cambioFiltro) paginaActual = 1; // filtro u orden distinto -> volver a la página 1
      firmaFiltro = firma;
      // Si solo se refrescó el contenido (panel en vivo) se mantiene la página actual sin animar
      render(cambioFiltro);
    }

    new MutationObserver(() => {
      if (programado) return;
      programado = true;
      requestAnimationFrame(revisarCambios);
    }).observe(contenedor, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] });

    firmaFiltro = firmaActual();
    render(false);
  }

  // ===================== APARICIÓN AL HACER SCROLL =====================
  function activarRevelado() {
    if (reducirMovimiento || !('IntersectionObserver' in window)) return;
    const objetivos = document.querySelectorAll(
      'main .card-custom:not(.modal .card-custom), main .producto-item, main .catalog-section-title'
    );
    const obs = new IntersectionObserver(entradas => {
      entradas.forEach(entrada => {
        if (entrada.isIntersecting) {
          entrada.target.classList.add('revelado');
          obs.unobserve(entrada.target);
        }
      });
    }, { rootMargin: '0px 0px -40px 0px', threshold: 0.05 });

    let indiceFila = 0;
    objetivos.forEach(el => {
      // Lo que ya está en pantalla al cargar aparece con un pequeño escalonado
      const r = el.getBoundingClientRect();
      if (r.top < window.innerHeight) el.style.transitionDelay = Math.min(indiceFila++ * 50, 300) + 'ms';
      el.classList.add('revelar');
      obs.observe(el);
      el.addEventListener('transitionend', () => { el.style.transitionDelay = ''; }, { once: true });
    });
  }

  // ===================== BOTÓN VOLVER ARRIBA =====================
  function activarVolverArriba() {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn-volver-arriba';
    btn.setAttribute('aria-label', 'Volver arriba');
    btn.innerHTML = '&uarr;';
    document.body.appendChild(btn);
    btn.addEventListener('click', () => window.scrollTo({ top: 0, behavior: reducirMovimiento ? 'auto' : 'smooth' }));
    const actualizar = () => btn.classList.toggle('visible', window.scrollY > 500);
    window.addEventListener('scroll', actualizar, { passive: true });
    actualizar();
  }

  // ===================== PANTALLA DE CARGA (primera visita) =====================
  function activarPantallaCarga() {
    const raiz = document.documentElement;
    const pantalla = document.getElementById('pantalla-carga');
    if (!pantalla) return;
    if (!raiz.classList.contains('con-carga')) { pantalla.remove(); return; }

    const inicio = performance.now();
    const MINIMO = reducirMovimiento ? 0 : 1900; // tiempo mínimo para que la torta alcance a armarse
    let cerrada = false;
    function cerrar() {
      if (cerrada) return;
      cerrada = true;
      try { sessionStorage.setItem('mb_carga_vista', '1'); } catch (e) { /* ignorar */ }
      const espera = Math.max(0, MINIMO - (performance.now() - inicio));
      setTimeout(() => {
        pantalla.classList.add('saliendo');
        raiz.classList.add('carga-lista');
        setTimeout(() => { raiz.classList.remove('con-carga'); pantalla.remove(); }, 650);
      }, espera);
    }
    if (document.readyState === 'complete') cerrar();
    else window.addEventListener('load', cerrar);
    setTimeout(cerrar, 4000); // nunca dejar al usuario esperando si una imagen tarda
  }

  // ===================== MENÚ PRINCIPAL =====================
  function activarMenu() {
    const menu = document.getElementById('menu-principal');
    if (menu) {
      const actualizar = () => menu.classList.toggle('menu-compacto', window.scrollY > 40);
      window.addEventListener('scroll', actualizar, { passive: true });
      actualizar();
    }
    // El contador del carrito "salta" cuando cambia su número
    document.querySelectorAll('.cart-counter').forEach(contador => {
      new MutationObserver(() => {
        contador.classList.remove('salto');
        void contador.offsetWidth;
        contador.classList.add('salto');
      }).observe(contador, { childList: true, characterData: true, subtree: true });
    });
  }

  // ===================== RED DE SEGURIDAD =====================
  // Si el navegador no está corriendo animaciones (ahorro de energía, pestaña congelada, etc.),
  // se muestra todo el contenido de inmediato para que nunca quede invisible.
  function seguroSinAnimaciones() {
    if (!document.timeline || typeof document.timeline.currentTime !== 'number') return;
    const inicio = document.timeline.currentTime;
    setTimeout(() => {
      if (document.visibilityState === 'visible' && document.timeline.currentTime === inicio) {
        document.documentElement.classList.add('sin-animaciones');
      }
    }, 2500);
  }

  // ===================== VENTANAS EMERGENTES (MODALES) =====================
  // Las animaciones del contenido (main, pestañas, tarjetas) crean capas propias; un modal dentro de
  // ellas quedaría DEBAJO del fondo oscuro y no se podría hacer clic. Por eso, justo antes de abrirse,
  // cada modal se mueve al <body>, al mismo nivel que su fondo.
  function activarModalesSeguros() {
    document.addEventListener('show.bs.modal', e => {
      const modal = e.target;
      if (modal.parentElement !== document.body) document.body.appendChild(modal);
    });
  }

  activarModalesSeguros();
  activarPantallaCarga();
  seguroSinAnimaciones();

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-paginar]').forEach(crearPaginador);
    activarRevelado();
    activarVolverArriba();
    activarMenu();
  });
})();
