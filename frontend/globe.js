// A slow-moving net of lines and dots (the grid of Vanta's "Globe" effect, three.js, with the sphere
// hidden) behind the lower part of the home page: from the Contract section down, in the page's colours. Loaded after the page is ready and
// skipped with "reduce motion" or without WebGL; if anything fails, the page is simply as it was.
(function () {
  const THREE_URL = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r134/three.min.js";
  const VANTA_URL = "https://cdn.jsdelivr.net/npm/vanta@0.5.24/dist/vanta.globe.min.js";

  const layer = document.getElementById("globe-bg");
  const start = document.getElementById("upload-form"); // the globe reaches no higher than this
  if (!layer || !start || matchMedia("(prefers-reduced-motion: reduce)").matches || !hasWebGL()) return;

  let effect = null;

  function hasWebGL() {
    try {
      const canvas = document.createElement("canvas");
      return Boolean(window.WebGLRenderingContext && (canvas.getContext("webgl") || canvas.getContext("experimental-webgl")));
    } catch {
      return false;
    }
  }

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = src;
      script.async = true;
      script.crossOrigin = "anonymous";
      script.onload = resolve;
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }

  // "#6b9bff" -> 0x6b9bff, from the CSS tokens so light and dark mode both match
  function token(name) {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    const hex = /^#([0-9a-f]{6})$/i.exec(value);
    return hex ? parseInt(hex[1], 16) : null;
  }

  function place() {
    const top = start.getBoundingClientRect().top + window.scrollY;
    layer.style.top = `${top}px`;
    layer.style.height = `${Math.max(document.documentElement.scrollHeight - top, 0)}px`;
    if (effect) effect.resize();
  }

  function create() {
    if (effect) effect.destroy();
    effect = window.VANTA.GLOBE({
      el: layer,
      mouseControls: true,
      touchControls: false,
      gyroControls: false,
      minHeight: 200,
      minWidth: 200,
      scale: 1,
      scaleMobile: 1,
      backgroundColor: token("--bg") ?? 0x0e0f10,
      color: token("--accent") ?? 0x6b9bff, // the net's lines and dots
      color2: token("--muted") ?? 0xa3a3a3,
    });
    // only the net: cont2 is the wireframe sphere and its rays
    if (effect.cont2) effect.cont2.visible = false;
    layer.classList.add("is-on");
  }

  window.addEventListener("load", () => {
    place();
    loadScript(THREE_URL)
      .then(() => loadScript(VANTA_URL))
      .then(create)
      .catch(() => layer.remove());
  });

  let pending = 0;
  window.addEventListener("resize", () => {
    cancelAnimationFrame(pending);
    pending = requestAnimationFrame(place);
  });
  // follow a switch between light and dark mode
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (window.VANTA) create();
  });
})();
