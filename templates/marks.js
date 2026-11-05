// Marks drawn over a photo: circle, arrow, box, label, spotlight, zoom. Shared by slide.html (still) and reel.html (animated).
// Every position is a fraction of the ORIGINAL picture: [x, y], 0,0 = top-left, 1,1 = bottom-right.
//   {"type": "circle", "at": [x, y], "r": 0.08, "label": "...", "side": "r"}   r = fraction of the picture's width; side r/l/t/b optional
//   {"type": "arrow", "to": [x, y], "from": [x, y], "label": "..."}    from is optional (auto: toward open space)
//   {"type": "box", "box": [x1, y1, x2, y2], "label": "..."}
//   {"type": "label", "at": [x, y], "label": "..."}                    a dot on the point with a tag beside it
//   {"type": "spotlight", "at": [x, y], "r": 0.2}                      darkens everything else
//   {"type": "zoom", "box": [x1, y1, x2, y2], "label": "..."}          enlarged copy of that area in the emptiest corner
// drawMarks(host, marks, W, H, src, opt) draws into `host` (an element W x H px laid exactly over the picture) and
// returns a function show(t): t = seconds since the marks started (Infinity = everything fully drawn).
// opt.view = {x0, y0, x1, y1}: the part of host that is actually visible and free of text; labels and insets stay inside it.
function drawMarks(host, marks, W, H, src, opt) {
  opt = opt || {};
  const Y = opt.color || "#FFD400", fs = opt.fontSize || 34, sw = opt.stroke || 9;
  const V = opt.view || {x0: 0, y0: 0, x1: W, y1: H}, M = 16;
  const NS = "http://www.w3.org/2000/svg";
  const P = a => [a[0] * W, a[1] * H];
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const ease = x => 1 - Math.pow(1 - clamp(x, 0, 1), 3);
  const back = x => { x = clamp(x, 0, 1); const c = 1.6; return 1 + (c + 1) * Math.pow(x - 1, 3) + c * Math.pow(x - 1, 2); };

  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("width", W); svg.setAttribute("height", H); svg.setAttribute("viewBox", "0 0 " + W + " " + H);
  svg.style.cssText = "position:absolute;left:0;top:0;overflow:visible;pointer-events:none;filter:drop-shadow(0 3px 9px rgba(0,0,0,.55))";
  host.appendChild(svg);
  const el = (tag, attrs, parent) => { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); (parent || svg).appendChild(e); return e; };
  const defs = el("defs", {});
  const steps = [];                                    // {at, dur, fn(p)} in order of appearance
  let clock = 0;
  const draw = (e, len) => { e.setAttribute("stroke-dasharray", len + " " + len); steps.push({at: clock, dur: .55, fn: p => e.setAttribute("stroke-dashoffset", len * (1 - ease(p)))}); clock += .4; };
  const pop = (e, isSvg) => { steps.push({at: clock, dur: .35, fn: p => { e.style.opacity = clamp(p * 2, 0, 1); e.style.transform = (isSvg ? "" : "") + "scale(" + (0.6 + 0.4 * back(p)) + ")"; }}); clock += .25; };
  const fade = (e, to) => { steps.push({at: clock, dur: .6, fn: p => e.style.opacity = to * ease(p)}); clock += .3; };

  function tag(text, x, y, side) {                     // yellow tag next to point (x, y); side r/l/t/b, kept inside the view
    const d = document.createElement("div");
    d.textContent = text;
    d.style.cssText = "position:absolute;left:0;top:0;background:" + Y + ";color:#000;font-weight:900;font-size:" + fs + "px;line-height:1.05;" +
      "padding:" + fs * .26 + "px " + fs * .42 + "px;text-transform:uppercase;letter-spacing:.02em;white-space:nowrap;box-shadow:0 4px 18px rgba(0,0,0,.5);opacity:0";
    host.appendChild(d);
    const w = d.offsetWidth, h = d.offsetHeight, g = fs * .55;
    const spot = sd => [sd === "r" ? x + g : sd === "l" ? x - w - g : x - w / 2, sd === "t" ? y - h - g : sd === "b" ? y + g : y - h / 2];
    const fits = ([a, b]) => a >= V.x0 + M && a + w <= V.x1 - M && b >= V.y0 + M && b + h <= V.y1 - M;
    const opposite = {r: "l", l: "r", t: "b", b: "t"};
    const order = [side, opposite[side], "t", "b", "r", "l"];    // the asked side first; never slide the tag over its own point
    let [lx, ly] = spot(order.find(sd => fits(spot(sd))) || side);
    lx = clamp(lx, V.x0 + M, V.x1 - w - M); ly = clamp(ly, V.y0 + M, V.y1 - h - M);
    d.style.left = lx + "px"; d.style.top = ly + "px"; d.style.transformOrigin = (x - lx) + "px " + (y - ly) + "px";
    pop(d);
    return d;
  }
  const sideAway = (x, y) => {                         // put a tag on the side with more room
    const cx = (V.x0 + V.x1) / 2, cy = (V.y0 + V.y1) / 2;
    return Math.abs(x - cx) / (V.x1 - V.x0) > Math.abs(y - cy) / (V.y1 - V.y0) ? (x < cx ? "r" : "l") : (y < cy ? "b" : "t");
  };

  const inView = a => { const [x, y] = P(a); return x >= V.x0 && x <= V.x1 && y >= V.y0 && y <= V.y1; };
  marks.forEach((m, n) => {
    const kind = m.type;
    const anchor = m.at || m.to || (m.box && [(m.box[0] + m.box[2]) / 2, (m.box[1] + m.box[3]) / 2]);
    if (anchor && !inView(anchor)) { console.warn("mark skipped, its point is outside the visible picture:", JSON.stringify(m)); return; }
    if (kind === "circle") {
      const [cx, cy] = P(m.at), r = (m.r || .08) * W;
      const c = el("circle", {cx, cy, r, fill: "none", stroke: Y, "stroke-width": sw, transform: "rotate(-90 " + cx + " " + cy + ")"});
      draw(c, 2 * Math.PI * r);
      const side = m.side || (cy < (V.y0 + V.y1) / 2 ? "b" : "t");
      if (m.label) tag(m.label, side === "r" ? cx + r : side === "l" ? cx - r : cx, side === "b" ? cy + r : side === "t" ? cy - r : cy, side);
    } else if (kind === "box") {
      const [x1, y1] = P(m.box), [x2, y2] = P(m.box.slice(2));
      const r = el("rect", {x: x1, y: y1, width: x2 - x1, height: y2 - y1, rx: 6, fill: "none", stroke: Y, "stroke-width": sw});
      draw(r, 2 * (x2 - x1 + y2 - y1));
      if (m.label) tag(m.label, (x1 + x2) / 2, y1 > V.y0 + fs * 2.2 ? y1 : y2, y1 > V.y0 + fs * 2.2 ? "t" : "b");
    } else if (kind === "label") {
      const [x, y] = P(m.at);
      const d = el("circle", {cx: x, cy: y, r: sw * 1.25, fill: Y, stroke: "#000", "stroke-width": 3, style: "opacity:0;transform-box:fill-box;transform-origin:center"});
      pop(d, true);
      clock -= .15;
      tag(m.label || "", x, y, m.side || sideAway(x, y));
    } else if (kind === "arrow") {
      const [tx, ty] = P(m.to);
      let fx, fy;
      if (m.from) [fx, fy] = P(m.from);
      else {
        let dx = (V.x0 + V.x1) / 2 - tx, dy = (V.y0 + V.y1) / 2 - ty, l = Math.hypot(dx, dy);
        if (l < 40) { dx = -1; dy = -1; l = Math.SQRT2; }
        const len = 0.3 * Math.min(V.x1 - V.x0, V.y1 - V.y0);
        fx = tx + dx / l * len; fy = ty + dy / l * len;
      }
      const ang = Math.atan2(ty - fy, tx - fx), gap = sw * 1.6, hl = sw * 3.6;
      const ex = tx - Math.cos(ang) * gap, ey = ty - Math.sin(ang) * gap;            // tip
      const bx = ex - Math.cos(ang) * hl * .8, by = ey - Math.sin(ang) * hl * .8;    // where the shaft ends
      const bend = (m.curve == null ? .18 : m.curve) * Math.hypot(bx - fx, by - fy);  // gentle curve
      const mx = (fx + bx) / 2 - Math.sin(ang) * bend, my = (fy + by) / 2 + Math.cos(ang) * bend;
      const shaft = el("path", {d: "M" + fx + " " + fy + " Q" + mx + " " + my + " " + bx + " " + by, fill: "none", stroke: Y, "stroke-width": sw, "stroke-linecap": "round"});
      draw(shaft, shaft.getTotalLength());
      const a2 = Math.atan2(by - my, bx - mx);
      const head = el("polygon", {points: [[ex, ey], [ex - Math.cos(a2 - .5) * hl, ey - Math.sin(a2 - .5) * hl], [ex - Math.cos(a2 + .5) * hl, ey - Math.sin(a2 + .5) * hl]].map(p => p.join(",")).join(" "),
        fill: Y, style: "opacity:0;transform-box:fill-box;transform-origin:center"});
      clock -= .2; pop(head, true);
      if (m.label) { const ddx = fx - tx, ddy = fy - ty; tag(m.label, fx, fy, Math.abs(ddx) > Math.abs(ddy) ? (ddx > 0 ? "r" : "l") : (ddy > 0 ? "b" : "t")); }
    } else if (kind === "spotlight") {
      const [cx, cy] = P(m.at), r = (m.r || .2) * W, big = 4 * Math.max(W, H);
      const s = el("path", {d: "M" + -big + " " + -big + "H" + big + "V" + big + "H" + -big + "Z M" + (cx + r) + " " + cy + " A" + r + " " + r + " 0 1 0 " + (cx - r) + " " + cy + " A" + r + " " + r + " 0 1 0 " + (cx + r) + " " + cy + "Z",
        fill: "rgba(0,0,0,.62)", "fill-rule": "evenodd", style: "opacity:0"});
      svg.insertBefore(s, svg.firstChild.nextSibling);   // under the other marks
      fade(s, 1);
      if (m.label) tag(m.label, cx, cy < (V.y0 + V.y1) / 2 ? cy + r : cy - r, cy < (V.y0 + V.y1) / 2 ? "b" : "t");
    } else if (kind === "zoom") {
      const [x1, y1] = P(m.box), [x2, y2] = P(m.box.slice(2)), rw = x2 - x1, rh = y2 - y1;
      const out = el("rect", {x: x1, y: y1, width: rw, height: rh, fill: "none", stroke: Y, "stroke-width": sw * .7});
      draw(out, 2 * (rw + rh));
      const vw = V.x1 - V.x0, vh = V.y1 - V.y0;
      let iw = vw * .44, ih = iw * rh / rw;
      if (ih > vh * .44) { ih = vh * .44; iw = ih * rw / rh; }
      const rcx = (x1 + x2) / 2, rcy = (y1 + y2) / 2;
      const ix = rcx < (V.x0 + V.x1) / 2 ? V.x1 - iw - M * 2 : V.x0 + M * 2;
      const iy = rcy < (V.y0 + V.y1) / 2 ? V.y1 - ih - M * 2 - (m.label ? fs * 1.8 : 0) : V.y0 + M * 2;
      const k = iw / rw, id = "zc" + n + Math.random().toString(36).slice(2, 6);
      el("rect", {x: ix, y: iy, width: iw, height: ih}, el("clipPath", {id}, defs));
      const g = el("g", {style: "opacity:0;transform-box:view-box;transform-origin:" + (ix + iw / 2) + "px " + (iy + ih / 2) + "px"});
      const near = [ix + (rcx < ix ? 0 : iw), iy + (rcy < iy ? 0 : ih)];
      el("line", {x1: clamp(near[0], x1, x2), y1: clamp(near[1], y1, y2), x2: near[0], y2: near[1], stroke: Y, "stroke-width": sw * .45}, g);
      el("image", {href: src, x: ix - x1 * k, y: iy - y1 * k, width: W * k, height: H * k, preserveAspectRatio: "none", "clip-path": "url(#" + id + ")"}, g);
      el("rect", {x: ix, y: iy, width: iw, height: ih, fill: "none", stroke: Y, "stroke-width": sw}, g);
      svg.appendChild(g);
      pop(g, true);
      if (m.label) tag(m.label, ix + iw / 2, iy + ih, "b");
    }
  });
  const show = t => steps.forEach(s => s.fn(clamp((t - s.at) / s.dur, 0, 1)));
  show(0);
  return show;
}

// The point a slide's camera/crop should keep in view: the given focus, or the middle of all marks.
function marksFocus(marks, focus) {
  if (focus) return focus;
  const pts = [];
  (marks || []).forEach(m => { ["at", "to", "from"].forEach(k => m[k] && pts.push(m[k])); if (m.box) pts.push([(m.box[0] + m.box[2]) / 2, (m.box[1] + m.box[3]) / 2]); });
  if (!pts.length) return null;
  return [pts.reduce((a, p) => a + p[0], 0) / pts.length, pts.reduce((a, p) => a + p[1], 0) / pts.length];
}
