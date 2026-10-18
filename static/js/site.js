(function () {
  "use strict";

  const body = document.body;
  const overlay = document.querySelector("[data-overlay]");
  const panels = {
    menu: document.querySelector("[data-panel='menu']"),
    search: document.querySelector("[data-panel='search']"),
  };

  function anyPanelOpen() {
    return Object.values(panels).some((panel) => panel && panel.classList.contains("open"));
  }

  function setBodyScrollLock() {
    body.style.overflow = anyPanelOpen() ? "hidden" : "";
    if (overlay) overlay.classList.toggle("visible", anyPanelOpen());
  }

  function openPanel(name) {
    Object.entries(panels).forEach(([key, panel]) => {
      if (!panel) return;
      panel.classList.toggle("open", key === name);
      panel.setAttribute("aria-hidden", key === name ? "false" : "true");
    });
    setBodyScrollLock();
    if (name === "search") {
      const input = panels.search && panels.search.querySelector("input");
      if (input) input.focus();
    }
  }

  function closeAllPanels() {
    Object.values(panels).forEach((panel) => {
      if (!panel) return;
      panel.classList.remove("open");
      panel.setAttribute("aria-hidden", "true");
    });
    setBodyScrollLock();
  }

  document.querySelectorAll("[data-open-panel]").forEach((trigger) => {
    trigger.addEventListener("click", () => openPanel(trigger.dataset.openPanel));
  });

  document.querySelectorAll("[data-close-panel]").forEach((trigger) => {
    trigger.addEventListener("click", closeAllPanels);
  });

  if (overlay) overlay.addEventListener("click", closeAllPanels);

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeAllPanels();
  });

  // Rail de productos (scroll horizontal con flechas)
  document.querySelectorAll("[data-rail]").forEach((rail) => {
    const id = rail.dataset.rail;
    document.querySelectorAll(`[data-rail-prev='${id}']`).forEach((btn) =>
      btn.addEventListener("click", () => rail.scrollBy({ left: -rail.clientWidth * 0.75, behavior: "smooth" }))
    );
    document.querySelectorAll(`[data-rail-next='${id}']`).forEach((btn) =>
      btn.addEventListener("click", () => rail.scrollBy({ left: rail.clientWidth * 0.75, behavior: "smooth" }))
    );
  });

  // Búsqueda (M10): sugerencias en el panel. Sin JS el formulario sigue
  // funcionando con un GET normal a catalog:search.
  const searchInput = document.querySelector("[data-search-input]");
  const suggestionsBox = document.querySelector("[data-search-suggestions]");

  if (searchInput && suggestionsBox) {
    const MIN_LENGTH = 2;
    const DEBOUNCE_MS = 250;
    let timer = null;
    let controller = null;

    function showMessage(text) {
      const p = document.createElement("p");
      p.textContent = text;
      suggestionsBox.replaceChildren(p);
    }

    function renderSuggestions(results, query) {
      if (!results.length) {
        showMessage(`No encontramos resultados para “${query}”.`);
        return;
      }
      const list = document.createElement("ul");
      list.className = "search-suggestion-list";
      results.forEach((item) => {
        const li = document.createElement("li");
        const link = document.createElement("a");
        link.className = "search-suggestion";
        link.href = item.url;
        if (item.image) {
          const img = document.createElement("img");
          img.src = item.image;
          img.alt = "";
          link.appendChild(img);
        }
        const text = document.createElement("span");
        text.className = "search-suggestion-text";
        const name = document.createElement("strong");
        name.textContent = item.name.toLowerCase();
        const meta = document.createElement("small");
        meta.textContent = `${item.category.toLowerCase()} · $${item.price}`;
        text.append(name, meta);
        link.appendChild(text);
        li.appendChild(link);
        list.appendChild(li);
      });
      const all = document.createElement("a");
      all.className = "search-view-all";
      all.href = `${searchInput.form.action}?q=${encodeURIComponent(query)}`;
      all.textContent = "ver todos los resultados";
      suggestionsBox.replaceChildren(list, all);
    }

    async function fetchSuggestions(query) {
      if (controller) controller.abort();
      controller = new AbortController();
      try {
        const response = await fetch(
          `${searchInput.dataset.suggestUrl}?q=${encodeURIComponent(query)}`,
          { signal: controller.signal, headers: { "X-Requested-With": "XMLHttpRequest" } }
        );
        if (!response.ok) return;
        const data = await response.json();
        renderSuggestions(data.results, query);
      } catch (error) {
        if (error.name !== "AbortError") suggestionsBox.replaceChildren();
      }
    }

    searchInput.addEventListener("input", () => {
      clearTimeout(timer);
      const query = searchInput.value.trim();
      if (query.length < MIN_LENGTH) {
        if (controller) controller.abort();
        suggestionsBox.replaceChildren();
        return;
      }
      timer = setTimeout(() => fetchSuggestions(query), DEBOUNCE_MS);
    });
  }

  // Selector de variante en la vista de producto (M11): actualiza precio,
  // stock, imagen, descripción y el formulario del carrito (variant_id,
  // cantidad máxima y botón). Es solo UI: la validación real de stock
  // ocurre en el servidor (carrito).
  const variantButtons = document.querySelectorAll("[data-variant-select]");
  const priceTarget = document.querySelector("[data-variant-price]");
  const stockTarget = document.querySelector("[data-variant-stock]");
  const imageTarget = document.querySelector("[data-variant-image]");
  const descriptionTarget = document.querySelector("[data-variant-description]");
  const variantIdInput = document.querySelector("[data-variant-id-input]");
  const quantityInput = document.querySelector("[data-quantity-input]");
  const addButton = document.querySelector("[data-add-button]");

  function clampQuantity() {
    if (!quantityInput || quantityInput.disabled) return;
    const max = parseInt(quantityInput.max, 10) || 1;
    const current = parseInt(quantityInput.value, 10);
    quantityInput.value = Number.isNaN(current) ? 1 : Math.min(Math.max(current, 1), max);
  }

  function syncAddForm(button) {
    const inStock = button.dataset.inStock === "true";
    const maxQty = parseInt(button.dataset.maxQty, 10) || 0;
    if (variantIdInput) variantIdInput.value = button.dataset.variantId;
    if (quantityInput) {
      quantityInput.disabled = !inStock;
      quantityInput.max = inStock ? maxQty : 1;
      clampQuantity();
    }
    if (addButton) {
      const cartReady = addButton.dataset.cartReady === "true";
      addButton.disabled = !inStock || !cartReady;
      addButton.textContent = inStock ? "añadir al carrito" : "agotado";
    }
  }

  if (quantityInput) quantityInput.addEventListener("change", clampQuantity);

  variantButtons.forEach((button) => {
    button.addEventListener("click", () => {
      variantButtons.forEach((btn) => {
        btn.classList.remove("active");
        btn.setAttribute("aria-pressed", "false");
      });
      button.classList.add("active");
      button.setAttribute("aria-pressed", "true");

      if (priceTarget && button.dataset.price) {
        priceTarget.textContent = `$${button.dataset.price}`;
      }
      if (stockTarget && button.dataset.stockLabel) {
        stockTarget.textContent = button.dataset.stockLabel;
        stockTarget.classList.remove("ok", "low", "out");
        stockTarget.classList.add(button.dataset.stockClass || "ok");
      }
      if (imageTarget) {
        imageTarget.src = button.dataset.image || imageTarget.dataset.fallbackSrc;
      }
      if (descriptionTarget && button.dataset.description) {
        descriptionTarget.textContent = button.dataset.description;
      }
      syncAddForm(button);
    });
  });
})();