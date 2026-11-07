// "Read what you sign" forms block by block: each dot of the dot-matrix font flickers on at its own time.
// The heading is drawn once onto an offscreen canvas at exactly the positions the browser laid it out,
// each dot is found as a separate blob of pixels, and the dots are copied onto a canvas over the heading
// one by one. When all are on, the canvas is removed and the real (selectable, responsive) text is shown.
(function () {
  const root = document.documentElement;
  const heading = document.querySelector(".hero .display");
  const FONT_TIMEOUT_MS = 1500; // no font by then: just show the text
  const SPREAD_MS = 1100; // the last dot starts flickering this long after the first
  const FLICKER_MS = 420;
  const MIN_DOT_PIXELS = 6; // smaller blobs are anti-aliasing specks, not dots
  // alpha steps over a dot's flicker: on, almost off, on, dim, on
  const FLICKER_STEPS = [
    [0.18, 1],
    [0.32, 0.1],
    [0.5, 0.85],
    [0.62, 0.25],
    [1, 1],
  ];

  function reveal() {
    root.classList.remove("hero-forming", "hero-animating");
  }

  if (!heading || !root.classList.contains("hero-forming")) {
    reveal();
    return;
  }

  const style = getComputedStyle(heading);
  const fontLoaded = document.fonts
    ? Promise.race([
        document.fonts.load(`${style.fontWeight} ${style.fontSize} Doto`).then((faces) => faces.length > 0),
        new Promise((resolve) => setTimeout(() => resolve(false), FONT_TIMEOUT_MS)),
      ])
    : Promise.resolve(false);

  fontLoaded
    .then((loaded) => (loaded ? animate() : reveal()))
    .catch(reveal);

  // every visible character with its on-screen box and colour (the accent word has its own)
  function characters() {
    const upper = style.textTransform === "uppercase";
    const walker = document.createTreeWalker(heading, NodeFilter.SHOW_TEXT);
    const found = [];
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const color = getComputedStyle(node.parentElement).color;
      for (let i = 0; i < node.data.length; i++) {
        const ch = node.data[i];
        if (!ch.trim()) continue;
        const range = document.createRange();
        range.setStart(node, i);
        range.setEnd(node, i + 1);
        found.push({ ch: upper ? ch.toUpperCase() : ch, rect: range.getBoundingClientRect(), color });
      }
    }
    return found;
  }

  // connected blobs of opaque pixels: one per dot
  function findDots(image) {
    const { width, height, data } = image;
    const seen = new Uint8Array(width * height);
    const dots = [];
    const stack = [];
    for (let start = 0; start < width * height; start++) {
      if (seen[start] || data[start * 4 + 3] < 100) continue;
      let minX = width, minY = height, maxX = 0, maxY = 0, count = 0;
      seen[start] = 1;
      stack.push(start);
      while (stack.length) {
        const p = stack.pop();
        const x = p % width;
        const y = (p - x) / width;
        count++;
        if (x < minX) minX = x;
        if (x > maxX) maxX = x;
        if (y < minY) minY = y;
        if (y > maxY) maxY = y;
        for (const q of [p - 1, p + 1, p - width, p + width]) {
          if (q < 0 || q >= width * height || seen[q]) continue;
          if ((q === p - 1 && x === 0) || (q === p + 1 && x === width - 1)) continue;
          if (data[q * 4 + 3] < 100) continue;
          seen[q] = 1;
          stack.push(q);
        }
      }
      if (count >= MIN_DOT_PIXELS) dots.push({ x: minX, y: minY, w: maxX - minX + 1, h: maxY - minY + 1 });
    }
    return dots;
  }

  function animate() {
    const dpr = window.devicePixelRatio || 1;
    const box = heading.getBoundingClientRect();
    const pad = parseFloat(style.fontSize) * 0.25; // glyphs overflow the tight line-height box
    const cssWidth = box.width + 2 * pad;
    const cssHeight = box.height + 2 * pad;

    const source = document.createElement("canvas");
    source.width = Math.ceil(cssWidth * dpr);
    source.height = Math.ceil(cssHeight * dpr);
    const sctx = source.getContext("2d", { willReadFrequently: true });
    sctx.scale(dpr, dpr);
    sctx.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
    for (const { ch, rect, color } of characters()) {
      sctx.fillStyle = color;
      const ascent = sctx.measureText(ch).fontBoundingBoxAscent;
      sctx.fillText(ch, rect.left - box.left + pad, rect.top - box.top + pad + ascent);
    }

    const dots = findDots(sctx.getImageData(0, 0, source.width, source.height));
    if (dots.length === 0) {
      reveal();
      return;
    }
    for (const dot of dots) {
      // mostly random, with a slight sweep from left to right
      dot.delay = Math.random() * SPREAD_MS * 0.75 + (dot.x / source.width) * SPREAD_MS * 0.25;
    }

    const canvas = document.createElement("canvas");
    canvas.className = "display-forming";
    canvas.setAttribute("aria-hidden", "true");
    canvas.width = source.width;
    canvas.height = source.height;
    canvas.style.width = `${cssWidth}px`;
    canvas.style.height = `${cssHeight}px`;
    canvas.style.left = `${-pad}px`;
    canvas.style.top = `${-pad}px`;
    heading.appendChild(canvas);
    root.classList.add("hero-animating"); // the CSS fallback reveal is no longer needed
    const ctx = canvas.getContext("2d");
    const started = performance.now();
    const end = SPREAD_MS + FLICKER_MS;

    function frame() {
      const t = performance.now() - started; // same clock as `started`, unlike the rAF timestamp
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      for (const dot of dots) {
        const progress = (t - dot.delay) / FLICKER_MS;
        if (progress <= 0) continue;
        const step = FLICKER_STEPS.find(([until]) => progress < until);
        ctx.globalAlpha = step ? step[1] : 1;
        // 1px margin keeps the anti-aliased edge of each dot
        const x = Math.max(dot.x - 1, 0), y = Math.max(dot.y - 1, 0);
        const w = Math.min(dot.w + 2, canvas.width - x), h = Math.min(dot.h + 2, canvas.height - y);
        ctx.drawImage(source, x, y, w, h, x, y, w, h);
      }
      if (t < end) {
        requestAnimationFrame(frame);
      } else {
        reveal(); // the real text now sits exactly under the finished canvas
        requestAnimationFrame(() => canvas.remove());
      }
    }
    requestAnimationFrame(frame);
  }
})();
