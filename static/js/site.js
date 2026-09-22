
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

  // Selector de variante en la vista de producto (botones): actualiza
  // precio, stock e imagen mostrada. Solo es UI — la validación real de
  // stock ocurre en servidor cuando se conecte el carrito, por eso el botón de "añadir al carrito" sigue deshabilitado.
  const variantButtons = document.querySelectorAll("[data-variant-select]");
  const priceTarget = document.querySelector("[data-variant-price]");
  const stockTarget = document.querySelector("[data-variant-stock]");
  const imageTarget = document.querySelector("[data-variant-image]");
  const descriptionTarget = document.querySelector("[data-variant-description]");

  variantButtons.forEach((button) => {
    button.addEventListener("click", () => {
      variantButtons.forEach((btn) => btn.classList.remove("active"));
      button.classList.add("active");

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
    });
  });
})();
