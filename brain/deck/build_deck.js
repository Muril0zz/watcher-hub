// AI Companion story deck. Build: NODE_PATH=<dir with pptxgenjs, react-icons, react, react-dom, sharp> node build_deck.js
// Every number on a slide is one we measured on our hardware or a cited source.
const path = require("path");
const pptxgen = require("pptxgenjs");
const React = require("react");
const { renderToStaticMarkup } = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa6");
const { applyTheme } = require(process.env.PPTX_SKILL + "/scripts/apply_theme.js");

const OUT = path.join(__dirname, "AI-Companion.pptx");
const HEX = {
  ink: "15233B", white: "FFFFFF", muted: "5B6B82", tint: "F2F5FA",
  orange: "FF6B2C", teal: "12B5A6", violet: "6C4DF6", red: "E5484D", green: "1F9D63", gold: "F5B700",
};
const THEME = {
  name: "AI Companion",
  headFontFace: "Arial",
  bodyFontFace: "Arial",
  colors: {
    dk1: HEX.ink, lt1: HEX.white, dk2: HEX.muted, lt2: HEX.tint,
    accent1: HEX.orange, accent2: HEX.teal, accent3: HEX.violet, accent4: HEX.red, accent5: HEX.green,
    accent6: HEX.gold, hlink: HEX.violet, folHlink: HEX.muted,
  },
};

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 x 7.5 in
pres.title = "AI Companion";
pres.author = "AI Companion team";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
const C = pres.SchemeColor;
const ACC = { orange: C.accent1, teal: C.accent2, violet: C.accent3, red: C.accent4, green: C.accent5, gold: C.accent6 };

// ---------- icons: react-icons -> PNG ----------
const iconCache = {};
async function icon(name, hex) {
  const key = name + hex;
  if (!iconCache[key]) {
    const svg = renderToStaticMarkup(React.createElement(fa[name], { color: "#" + hex, size: 256 }));
    const png = await sharp(Buffer.from(svg)).resize(256, 256).png().toBuffer();
    iconCache[key] = "image/png;base64," + png.toString("base64");
  }
  return iconCache[key];
}

// Charts are drawn as SVG -> PNG: Keynote (what the team presents with) drops pptxgenjs native charts.
const DPI = 200, pt = (n) => (n * DPI) / 72;
async function svgImage(svg) {
  return "image/png;base64," + (await sharp(Buffer.from(svg)).png().toBuffer()).toString("base64");
}
const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;");

function lineChartSvg({ w, h, title, xs, series, yMin, yMax, yStep, xLabel }) {
  const W = w * DPI, H = h * DPI, L = pt(30), R = pt(8), T = pt(30), B = pt(56);
  const px = (x) => L + ((x - xs[0]) / (xs[xs.length - 1] - xs[0])) * (W - L - R);
  const py = (y) => T + ((yMax - y) / (yMax - yMin)) * (H - T - B);
  let g = `<text x="0" y="${pt(14)}" font-family="Arial" font-size="${pt(14)}" font-weight="bold" fill="#${HEX.ink}">${esc(title)}</text>`;
  for (let y = yMin; y <= yMax; y += yStep) {
    g += `<line x1="${L}" x2="${W - R}" y1="${py(y)}" y2="${py(y)}" stroke="#E3E8F0" stroke-width="2"/>`;
    g += `<text x="${L - pt(4)}" y="${py(y) + pt(3.5)}" text-anchor="end" font-family="Arial" font-size="${pt(10)}" fill="#${HEX.muted}">${y}°</text>`;
  }
  for (let x = 0; x <= Math.floor(xs[xs.length - 1]); x++) {
    g += `<text x="${px(x)}" y="${py(yMin) + pt(14)}" text-anchor="middle" font-family="Arial" font-size="${pt(10)}" fill="#${HEX.muted}">${x}</text>`;
  }
  g += `<text x="${(L + W - R) / 2}" y="${py(yMin) + pt(28)}" text-anchor="middle" font-family="Arial" font-size="${pt(10)}" fill="#${HEX.muted}">${esc(xLabel)}</text>`;
  let lx = L;
  for (const s of series) {
    const d = s.values.map((v, i) => `${i ? "L" : "M"}${px(xs[i]).toFixed(1)},${py(v).toFixed(1)}`).join(" ");
    g += `<path d="${d}" fill="none" stroke="#${s.color}" stroke-width="${pt(2.4)}" stroke-linejoin="round" stroke-linecap="round"/>`;
    const ly = H - pt(8);
    g += `<rect x="${lx}" y="${ly - pt(8)}" width="${pt(14)}" height="${pt(5)}" rx="${pt(2)}" fill="#${s.color}"/>`;
    g += `<text x="${lx + pt(18)}" y="${ly}" font-family="Arial" font-size="${pt(11)}" fill="#${HEX.ink}">${esc(s.name)}</text>`;
    lx += pt(18) + pt(11) * 0.52 * s.name.length + pt(16);
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${g}</svg>`;
}

function barChartSvg({ w, h, title, bars, max, unit }) {
  const W = w * DPI, H = h * DPI, L = pt(118), top = pt(50), bh = pt(44), gap = pt(30);
  let g = "";
  title.forEach((line, i) => {
    g += `<text x="0" y="${pt(14) + i * pt(18)}" font-family="Arial" font-size="${pt(14)}" font-weight="bold" fill="#${HEX.ink}">${esc(line)}</text>`;
  });
  bars.forEach(([label, v, color], i) => {
    const y = top + i * (bh + gap), bw = (v / max) * (W - L - pt(60));
    g += `<text x="${L - pt(8)}" y="${y + bh / 2 + pt(4.5)}" text-anchor="end" font-family="Arial" font-size="${pt(13)}" fill="#${HEX.ink}">${esc(label)}</text>`;
    g += `<rect x="${L}" y="${y}" width="${bw}" height="${bh}" rx="${pt(4)}" fill="#${color}"/>`;
    g += `<text x="${L + bw + pt(8)}" y="${y + bh / 2 + pt(6)}" font-family="Arial" font-size="${pt(18)}" font-weight="bold" fill="#${HEX.ink}">${v.toFixed(1)}${unit}</text>`;
  });
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">${g}</svg>`;
}

// motif: an icon in a colored circle
async function badge(slide, name, fill, x, y, d, id, iconHex = HEX.white) {
  slide.addShape(pres.shapes.OVAL, { x, y, w: d, h: d, fill: { color: fill }, line: { color: fill, width: 0 }, objectName: id + "-circle" });
  const s = d * 0.52;
  slide.addImage({ data: await icon(name, iconHex), x: x + (d - s) / 2, y: y + (d - s) / 2, w: s, h: s, objectName: id + "-icon", altText: name });
}

function card(slide, x, y, w, h, id, fill = C.background2) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x, y, w, h, rectRadius: 0.12, fill: { color: fill }, line: { color: fill, width: 0 }, objectName: id,
  });
}

function text(slide, t, opts) {
  slide.addText(t, { isTextBox: true, margin: 0, valign: "top", fontSize: 16, color: C.text1, ...opts });
}

function arrow(slide, x, y, w, id, color = C.text2) {
  slide.addShape(pres.shapes.LINE, { x, y, w, h: 0, line: { color, width: 2.5, endArrowType: "triangle" }, objectName: id });
}

// ---------- layouts ----------
const FOOTER = "AI Companion · ShanHaiWoo Hardware Hackathon · Shanghai 2026";
pres.defineSlideMaster({
  title: "TITLE_DARK",
  background: { color: C.text1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.8, y: 1.55, w: 7.6, h: 2.6, fontSize: 40, bold: true, color: C.background1, valign: "top", align: "left", margin: 0 }, text: "" } },
  ],
});
pres.defineSlideMaster({
  title: "CONTENT",
  background: { color: C.background1 },
  margin: [0.4, 0.6, 0.6, 0.6],
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.4, w: 12.1, h: 1.25, fontSize: 32, bold: true, color: C.text1, valign: "top", align: "left", margin: 0 }, text: "" } },
    { text: { text: FOOTER, options: { x: 0.6, y: 7.0, w: 9, h: 0.3, fontSize: 10, color: C.text2, margin: 0 } } },
  ],
  slideNumber: { x: 12.2, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: C.text2, align: "right" },
});
pres.defineSlideMaster({
  title: "CONTENT_DARK",
  background: { color: C.text1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: 0.6, y: 0.4, w: 12.1, h: 1.25, fontSize: 32, bold: true, color: C.background1, valign: "top", align: "left", margin: 0 }, text: "" } },
    { text: { text: FOOTER, options: { x: 0.6, y: 7.0, w: 9, h: 0.3, fontSize: 10, color: C.background2, margin: 0 } } },
  ],
  slideNumber: { x: 12.2, y: 7.0, w: 0.5, h: 0.3, fontSize: 10, color: C.background2, align: "right" },
});

async function build() {
  // ===== 1. Title =====
  pres.addSection({ title: "Why" });
  let s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Why" });
  text(s, "AI COMPANION", { x: 0.8, y: 0.9, w: 7, h: 0.4, fontSize: 18, bold: true, color: ACC.orange, charSpacing: 4 });
  s.addText("Say it any way, in any language, and it lends a hand", { placeholder: "title" });
  const chips = [
    ["FaEarListen", HEX.teal, "Marco listens"],
    ["FaBrain", HEX.violet, "Claude understands"],
    ["FaHand", HEX.orange, "The arm does it"],
  ];
  for (let i = 0; i < chips.length; i++) {
    const [ic, col, label] = chips[i];
    const y = 4.35 + i * 0.62;
    await badge(s, ic, col, 0.8, y, 0.46, "chip" + i);
    text(s, label, { x: 1.45, y: y + 0.06, w: 5, h: 0.4, fontSize: 18, color: C.background1, bold: true });
  }
  text(s, "ShanHaiWoo Hardware Hackathon · Shanghai · October 21–23, 2026", { x: 0.8, y: 6.55, w: 8, h: 0.35, fontSize: 14, color: C.background2 });
  await badge(s, "FaHandHoldingHeart", HEX.orange, 8.9, 1.55, 3.6, "hero");
  s.addNotes("0:00. This is AI Companion. You talk to it the way you talk to a person, in any language, and it lends you a hand. Marco, the little Watcher, listens; Claude understands what you meant; the robot arm does it.");

  // ===== 2. One in five =====
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Why" });
  s.addText("One in five people in China is now over 60", { placeholder: "title" });
  text(s, "297M", { x: 0.6, y: 2.0, w: 5.6, h: 1.4, fontSize: 96, bold: true, color: ACC.orange });
  text(s, "people aged 60 or older at the end of 2023", { x: 0.6, y: 3.45, w: 5.6, h: 0.4, fontSize: 18, color: C.text2 });
  text(s, "21.1%", { x: 0.6, y: 4.2, w: 5.6, h: 1.2, fontSize: 72, bold: true, color: ACC.teal });
  text(s, "of the whole population", { x: 0.6, y: 5.35, w: 5.6, h: 0.4, fontSize: 18, color: C.text2 });
  for (let i = 0; i < 5; i++) {
    const old = i === 2;
    const x = 6.9 + i * 1.18;
    card(s, x, 2.3, 1.0, 3.0, "person-card" + i, old ? ACC.orange : C.background2);
    s.addImage({ data: await icon(old ? "FaPersonCane" : "FaPerson", old ? HEX.white : HEX.muted), x: x + 0.15, y: 3.0, w: 0.7, h: 1.4, sizing: { type: "contain", w: 0.7, h: 1.4 }, objectName: "person" + i, altText: old ? "older person" : "person" });
  }
  text(s, "1 in 5", { x: 6.9, y: 5.5, w: 5.8, h: 0.5, fontSize: 20, bold: true, color: ACC.orange, align: "center" });
  text(s, "Source: National Bureau of Statistics, reported by Caixin Global, September 5, 2024", { x: 0.6, y: 6.45, w: 12, h: 0.3, fontSize: 11, color: C.text2 });
  s.addNotes("0:10. One in five people in China is now over sixty: almost three hundred million people. Many of them spend most of the day at home, at a table, and small physical help matters.");

  // ===== 3. The gap =====
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Why" });
  s.addText("Today, the voice in the room can talk, but it can't hand you anything", { placeholder: "title" });
  const cols = [
    { name: "Smart speaker", ic: "FaVolumeHigh", col: HEX.muted, fill: C.background2, rows: [[1, "Talks and answers"], [1, "Understands free speech"], [0, "No hands: it can't do anything physical"]] },
    { name: "Robot arm", ic: "FaRobot", col: HEX.muted, fill: C.background2, rows: [[1, "Has hands"], [0, "Needs an app, menus or exact commands"], [0, "Usually one language, no dialects"]] },
    { name: "AI Companion", ic: "FaHandHoldingHeart", col: HEX.orange, fill: C.background2, rows: [[1, "Talks back in your language"], [1, "Has hands"], [1, "Any wording, slang, dialect or correction"]] },
  ];
  for (let i = 0; i < cols.length; i++) {
    const c = cols[i], x = 0.6 + i * 4.1;
    card(s, x, 1.95, 3.8, 4.7, "gap-card" + i, c.fill);
    await badge(s, c.ic, c.col, x + 0.35, 2.3, 0.8, "gap-badge" + i);
    text(s, c.name, { x: x + 1.35, y: 2.5, w: 2.3, h: 0.45, fontSize: 22, bold: true, color: i === 2 ? ACC.orange : C.text1 });
    for (let r = 0; r < c.rows.length; r++) {
      const [okRow, line] = c.rows[r], y = 3.55 + r * 0.95;
      s.addImage({ data: await icon(okRow ? "FaCircleCheck" : "FaCircleXmark", okRow ? HEX.green : HEX.red), x: x + 0.35, y: y + 0.03, w: 0.32, h: 0.32, objectName: `gap-mark${i}-${r}`, altText: okRow ? "yes" : "no" });
      text(s, line, { x: x + 0.85, y, w: 2.75, h: 0.8, fontSize: 16 });
    }
  }
  s.addNotes("0:20. The voice assistants in their homes can talk, but they can't hand anyone anything. The robots that could need apps, menus and one language. Nobody puts the two together for someone who just wants to say it in their own words.");

  // ===== 4. The solution =====
  pres.addSection({ title: "What we built" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "What we built" });
  s.addText("With AI Companion, Marco hears you, Claude understands, the arm does it", { placeholder: "title" });
  const flow = [
    ["FaEarListen", HEX.teal, "Ears: Marco", "A SenseCAP Watcher on the table. Say “Marco” and talk."],
    ["FaBrain", HEX.violet, "Brain: Claude", "Understands slang, dialect and corrections, and plans the movement."],
    ["FaHand", HEX.orange, "Hands: the arm", "Moves, or shakes “no” and says kindly why it can't."],
  ];
  for (let i = 0; i < flow.length; i++) {
    const [ic, col, head, body] = flow[i], x = 0.6 + i * 4.2;
    await badge(s, ic, col, x + 1.05, 1.95, 1.5, "flow" + i);
    text(s, head, { x, y: 3.6, w: 3.6, h: 0.45, fontSize: 22, bold: true, align: "center" });
    text(s, body, { x: x + 0.2, y: 4.1, w: 3.2, h: 0.9, fontSize: 16, color: C.text2, align: "center" });
    if (i < 2) arrow(s, x + 3.75, 2.7, 0.75, "flow-arrow" + i);
  }
  card(s, 0.6, 5.35, 12.1, 1.3, "example");
  text(s, [
    { text: "“Marco, vai tudo pra baixo e acena”", options: { bold: true, color: ACC.violet } },
    { text: "   →   “Claro!”   →   ", options: { color: C.text2 } },
    { text: "it bows all the way down, then waves", options: { bold: true, color: ACC.orange } },
  ], { x: 0.95, y: 5.55, w: 11.4, h: 0.45, fontSize: 17 });
  text(s, "Portuguese, “all the way” and two moves in a row, understood in one sentence", { x: 0.95, y: 6.1, w: 11.4, h: 0.4, fontSize: 14, color: C.text2 });
  s.addNotes("0:35. With AI Companion, Marco listens, Claude understands what you meant, even with slang, dialect or a correction, and the arm does it, or says kindly why it can't.");

  // ===== 5. Architecture =====
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "What we built" });
  s.addText("Where the AI runs and where the hardware sits", { placeholder: "title" });
  // A: Marco
  card(s, 0.6, 1.95, 3.2, 4.7, "arch-marco");
  await badge(s, "FaEarListen", HEX.teal, 0.9, 2.2, 0.8, "arch-marco-badge");
  text(s, "Marco", { x: 1.85, y: 2.3, w: 1.8, h: 0.4, fontSize: 22, bold: true });
  text(s, "SenseCAP Watcher", { x: 1.85, y: 2.7, w: 1.9, h: 0.3, fontSize: 12, color: C.text2 });
  text(s, [
    { text: "Wake word “Marco”", options: { bullet: true, breakLine: true } },
    { text: "Microphone and speaker", options: { bullet: true, breakLine: true } },
    { text: "USB today; Wi-Fi through its MCP access point", options: { bullet: true } },
  ], { x: 0.9, y: 3.4, w: 2.7, h: 2.6, fontSize: 15, paraSpaceAfter: 8 });
  arrow(s, 3.85, 4.3, 0.6, "arch-arrow1");
  // B: Mac brain
  card(s, 4.5, 1.95, 4.5, 4.7, "arch-mac");
  await badge(s, "FaLaptop", HEX.violet, 4.8, 2.2, 0.8, "arch-mac-badge");
  text(s, "MacBook: the brain", { x: 5.75, y: 2.4, w: 3.1, h: 0.4, fontSize: 22, bold: true });
  const layers = [
    ["Whisper small, on the Mac", "Speech to text in ~0.9 s, detects the language"],
    ["Fast path  |  Claude Haiku 5.5", "Short commands run instantly; anything else becomes JSON intents + a reply"],
    ["Safety layer, 30 times a second", "Safe ranges, contact guard, “stop” always wins"],
  ];
  for (let i = 0; i < layers.length; i++) {
    const y = 3.25 + i * 1.1;
    card(s, 4.8, y, 3.9, 0.95, "arch-layer" + i, C.background1);
    text(s, layers[i][0], { x: 5.0, y: y + 0.1, w: 3.6, h: 0.3, fontSize: 14, bold: true, color: ACC.violet });
    text(s, layers[i][1], { x: 5.0, y: y + 0.42, w: 3.6, h: 0.5, fontSize: 12, color: C.text2 });
  }
  arrow(s, 9.05, 4.3, 0.6, "arch-arrow2");
  // C: arms
  card(s, 9.7, 1.95, 3.0, 2.25, "arch-black");
  await badge(s, "FaHand", HEX.orange, 9.95, 2.15, 0.7, "arch-black-badge");
  text(s, "Black arm", { x: 10.8, y: 2.3, w: 1.8, h: 0.4, fontSize: 20, bold: true });
  text(s, "SO-101, 6 joints, 5 V. Runs today's demo", { x: 9.95, y: 3.05, w: 2.6, h: 0.9, fontSize: 14, color: C.text2 });
  card(s, 9.7, 4.4, 3.0, 2.25, "arch-white");
  await badge(s, "FaCamera", HEX.muted, 9.95, 4.6, 0.7, "arch-white-badge");
  text(s, "White arm", { x: 10.8, y: 4.75, w: 1.8, h: 0.4, fontSize: 20, bold: true });
  text(s, "SO-101 + wrist camera; Claude Opus 5.5 sees and plans. Needs a new elbow servo", { x: 9.95, y: 5.45, w: 2.6, h: 1.1, fontSize: 14, color: C.text2 });
  s.addNotes("0:50. Marco is the ears, the arm is the hands, the camera is the eyes, and the brain runs on this laptop. Whisper turns speech into text locally, short commands run instantly, everything else goes to Claude, and a safety layer checks every pose thirty times a second before the motors move. Let me show you.");

  // ===== 6. Any language =====
  pres.addSection({ title: "Proof" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Proof" });
  s.addText("Say it any way, in any language, and it does it or tells you why not", { placeholder: "title" });
  const hdr = (t) => ({ text: t, options: { bold: true, color: C.background1, fill: { color: C.text1 }, fontSize: 15 } });
  const rows = [
    ["向右转一点", "Mandarin", "Turns right a little, answers in Mandarin"],
    ["舉高少少", "Cantonese", "Raises a little, answers in Cantonese"],
    ["gira todo a la derecha", "Spanish", "Turns all the way right"],
    ["पूरा दाईं ओर घूमो", "Hindi", "Turns all the way right"],
    ["vira tudo pra direita e depois tudo pra esquerda", "Portuguese", "All the way right, then all the way left"],
    ["left, no, right", "English", "Only right: the correction wins"],
    ["bring me a glass of water", "English", "Says kindly it can't, shakes “no”"],
    ["we're having lunch later (side chat)", "English", "Stays still and silent"],
  ];
  const tableRows = [[hdr("What someone said"), hdr("Language"), hdr("What the arm did")]];
  rows.forEach((r, i) => {
    const fill = { color: i % 2 ? C.background1 : C.background2 };
    tableRows.push([
      { text: r[0], options: { bold: true, fill, color: C.text1 } },
      { text: r[1], options: { fill, color: C.text2 } },
      { text: r[2], options: { fill, color: C.text1 } },
    ]);
  });
  s.addTable(tableRows, { x: 0.6, y: 1.9, w: 12.1, colW: [5.0, 2.0, 5.1], rowH: 0.5, fontSize: 15, valign: "middle", margin: [0, 0.15, 0, 0.15], border: { type: "none" }, objectName: "language-table" });
  text(s, "Real phrases from our test suites; Cantonese is detected and answered in Cantonese, with Traditional characters", { x: 0.6, y: 6.55, w: 12.1, h: 0.3, fontSize: 11, color: C.text2 });
  s.addNotes("Every row here is a phrase from our automated test suite, run against the real model. Note the correction: 'left, no, right' turns only right. And when someone at the table is just chatting, the arm stays still and quiet.");

  // ===== 7. Any movement =====
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Proof" });
  s.addText("Not a menu of moves: any movement the arm can physically make", { placeholder: "title" });
  const joints = [
    ["B", "Base", "turns the arm, −95° to +95°", HEX.ink],
    ["1", "Number 1, shoulder", "leans back or forward", HEX.orange],
    ["2", "Number 2, elbow", "forearm up or down", HEX.teal],
    ["3", "Number 3, wrist bend", "−60° to +60°", HEX.violet],
    ["4", "Number 4, wrist turn", "−170° to +170°", HEX.muted],
    ["H", "Hand", "open or close", HEX.gold],
  ];
  joints.forEach(([k, head, body, col], i) => {
    const y = 1.95 + i * 0.72;
    s.addShape(pres.shapes.OVAL, { x: 0.6, y, w: 0.52, h: 0.52, fill: { color: col }, line: { color: col, width: 0 }, objectName: "joint-dot" + i });
    text(s, k, { x: 0.6, y: y + 0.08, w: 0.52, h: 0.36, fontSize: 16, bold: true, color: C.background1, align: "center" });
    text(s, head, { x: 1.3, y: y + 0.0, w: 3.6, h: 0.3, fontSize: 15, bold: true });
    text(s, body, { x: 1.3, y: y + 0.3, w: 3.6, h: 0.3, fontSize: 12, color: C.text2 });
  });
  text(s, "“Move number 2 all the way down” · “do a snake” · “draw an 8 in the air” · “bend each joint one at a time”", { x: 0.6, y: 6.3, w: 4.4, h: 0.6, fontSize: 12, color: ACC.violet, italic: true });
  // measured on the black arm, Oct 23: "do a snake", every 0.5 s (degrees)
  const t = [0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.1, 6.6, 7.1, 7.6];
  const base = [-60.2, -27.2, 30.5, 6.9, -11.5, -40.4, -13.9, -8.4, 29.2, 9.5, -12.3, -38.5, -9.5, 13.8, 7.6, -9.5];
  const sh = [-0.4, 9.5, 26.5, 25.7, 25.9, 27.0, 25.1, 25.3, 26.9, 25.0, 26.8, 25.4, 22.6, 25.2, 22.6, 22.6];
  const el = [-95.3, -85.7, -64.5, -45.9, -45.9, -47.4, -45.5, -45.5, -45.7, -44.2, -47.6, -49.8, -47.0, -47.1, -47.4, -47.1];
  const wr = [-1.8, -31.2, -29.7, -5.8, 30.9, -15.3, -6.8, 36.3, -29.0, 14.6, 6.9, -34.5, 16.2, 11.5, -5.5, 31.3];
  const snake = lineChartSvg({
    w: 7.4, h: 4.75, title: "Measured on our arm: “do a snake”", xs: t, yMin: -100, yMax: 60, yStep: 20, xLabel: "seconds",
    series: [
      { name: "Base", values: base, color: HEX.ink },
      { name: "No. 1 shoulder", values: sh, color: HEX.orange },
      { name: "No. 2 elbow", values: el, color: HEX.teal },
      { name: "No. 3 wrist", values: wr, color: HEX.violet },
    ],
  });
  s.addImage({ data: await svgImage(snake), x: 5.3, y: 1.9, w: 7.4, h: 4.75, objectName: "snake-chart",
    altText: "Joint angles while doing a snake: shoulder holds about +25 degrees and elbow about -46 degrees, while base swings -40 to +30 and wrist -35 to +36" });
  s.addNotes("This is the part we're proudest of. It isn't a fixed list of moves. Each joint has a name, base and numbers one to four plus the hand, and Claude writes its own choreography, up to forty poses, which the server clamps to safe ranges. This chart is real data from our arm: someone said 'do a snake' in English. The shoulder leans forward and the elbow stretches out, while the base and the wrist swing back and forth.");

  // ===== 8. Live demo =====
  s = pres.addSlide({ masterName: "CONTENT_DARK", sectionTitle: "Proof" });
  s.addText("Live demo: six things to try in two minutes", { placeholder: "title" });
  const demo = [
    ["“Marco, turn left”, then “go all the way down and wave”", "Sequences and “all the way”"],
    ["“向右转一点”, then “舉高少少”", "Mandarin, then Cantonese"],
    ["“Left, no, right”", "The correction wins"],
    ["“Do a snake”, then “move number 2 all the way up”", "Free movement, named joints"],
    ["“Bring me a glass of water”", "A kind no, and a head shake"],
    ["“Stop!” in the middle of a move", "Stop always wins"],
  ];
  for (let i = 0; i < demo.length; i++) {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 0.6 + col * 6.15, y = 1.95 + row * 1.5;
    card(s, x, y, 5.95, 1.3, "demo-card" + i, "22324F");
    s.addShape(pres.shapes.OVAL, { x: x + 0.3, y: y + 0.35, w: 0.6, h: 0.6, fill: { color: ACC.orange }, line: { color: ACC.orange, width: 0 }, objectName: "demo-num" + i });
    text(s, String(i + 1), { x: x + 0.3, y: y + 0.45, w: 0.6, h: 0.4, fontSize: 18, bold: true, color: C.background1, align: "center" });
    text(s, demo[i][0], { x: x + 1.15, y: y + 0.22, w: 4.6, h: 0.55, fontSize: 16, bold: true, color: C.background1 });
    text(s, demo[i][1], { x: x + 1.15, y: y + 0.82, w: 4.6, h: 0.35, fontSize: 13, color: "AEB9CC" });
  }
  text(s, "If Wi-Fi or Marco fails: the hold-to-talk button on the Mac page. If the API fails: short commands still run offline.", { x: 0.6, y: 6.5, w: 12.1, h: 0.3, fontSize: 12, color: "AEB9CC" });
  s.addNotes("Keep Marco's volume down so the Mac is the one voice. A teammate does the Mandarin and Cantonese lines. Someone chats beside the arm to show it ignores side conversations. Fallback: hold-to-talk on the Mac page; with no API, short commands still work through the keyword path.");

  // ===== 9. Safe by design =====
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Proof" });
  s.addText("Safe by design: it knows what it can't do", { placeholder: "title" });
  const safe = [
    ["FaBan", HEX.red, "Refuses out loud", "Impossible asks get a kind sentence in the speaker's language and a “no” shake. It never pretends."],
    ["FaCircleStop", HEX.orange, "“Stop” always wins", "“Stop”, “para” or “停” cancels any sequence at once, even while Claude is still thinking."],
    ["FaCommentSlash", HEX.teal, "Ignores side conversations", "Chatting, laughter and speech-recognition junk are marked “not for the robot”: the arm stays still."],
    ["FaShieldHalved", HEX.violet, "Never reaches the table", "Every pose is clamped to safe ranges; a joint that strains without moving freezes in under a second."],
  ];
  for (let i = 0; i < safe.length; i++) {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 0.6 + col * 6.15, y = 1.95 + row * 2.05;
    card(s, x, y, 5.95, 1.85, "safe-card" + i);
    await badge(s, safe[i][0], safe[i][1], x + 0.3, y + 0.3, 0.85, "safe-badge" + i);
    text(s, safe[i][2], { x: x + 1.4, y: y + 0.3, w: 4.3, h: 0.4, fontSize: 20, bold: true });
    text(s, safe[i][3], { x: x + 1.4, y: y + 0.78, w: 4.35, h: 0.95, fontSize: 15, color: C.text2 });
  }
  text(s, "Claude decides; the safety layer enforces.", { x: 0.6, y: 6.2, w: 12.1, h: 0.45, fontSize: 20, italic: true, bold: true, color: ACC.violet });
  s.addNotes("Is it safe around elderly people? Low torque limits, a contact guard that freezes the arm, a stop word that always wins, and Claude refuses anything unsafe. It is a small desk arm, not a mobile robot. Claude decides; the safety layer enforces.");

  // ===== 10. Numbers =====
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Proof" });
  s.addText("Measured, not promised: real languages, real latency", { placeholder: "title" });
  const stats = [
    ["80/80", "command phrases right in 6 languages", ACC.orange],
    ["12/12", "free-movement phrases (snake, figure 8, named joints)", ACC.violet],
    ["17/17", "noise and side-chat tests ignored", ACC.teal],
    ["~1 s", "for common commands; ~3 s for free speech", C.text1],
  ];
  for (let i = 0; i < stats.length; i++) {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 0.6 + col * 3.35, y = 1.95 + row * 2.4;
    text(s, stats[i][0], { x, y, w: 3.15, h: 1.0, fontSize: 54, bold: true, color: stats[i][2] });
    text(s, stats[i][1], { x, y: y + 1.05, w: 3.0, h: 0.9, fontSize: 15, color: C.text2 });
  }
  card(s, 7.4, 1.95, 5.3, 4.3, "latency-card");
  const lat = barChartSvg({
    w: 4.8, h: 2.4, title: ["Why Haiku drives the arm:", "seconds per command from Shanghai"], max: 6.5, unit: " s",
    bars: [["Haiku 5.5", 1.7, HEX.violet], ["Opus 5.5", 5.6, HEX.muted]],
  });
  s.addImage({ data: await svgImage(lat), x: 7.65, y: 2.25, w: 4.8, h: 2.4, objectName: "latency-chart",
    altText: "Seconds per command: Claude Haiku 5.5 1.7 s, Claude Opus 5.5 5.6 s" });
  text(s, "Same intents on our test phrases. Opus 5.5 plans the camera-based picking, where it has time to think.", { x: 7.65, y: 5.0, w: 4.8, h: 0.9, fontSize: 14, color: C.text2 });
  s.addNotes("Every number here we measured ourselves this week. Eighty out of eighty test phrases in Mandarin, Cantonese, English, Portuguese, Spanish and Hindi. We picked the fastest Claude model for the arm because both gave the same answers, and a person waiting for a hand shouldn't wait five seconds.");

  // ===== 11. What broke =====
  pres.addSection({ title: "Next" });
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Next" });
  s.addText("What broke: the white arm's elbow, and we proved it by measuring", { placeholder: "title" });
  const servos = [["Base", 1], ["Shoulder", 1], ["Elbow", 0], ["Wrist bend", 1], ["Wrist turn", 1], ["Gripper", 1]];
  for (let i = 0; i < servos.length; i++) {
    const [name, good] = servos[i], col = i % 3, row = Math.floor(i / 3);
    const x = 0.6 + col * 2.1, y = 1.95 + row * 1.55;
    card(s, x, y, 1.9, 1.35, "servo-card" + i, good ? C.background2 : ACC.red);
    s.addImage({ data: await icon(good ? "FaCircleCheck" : "FaCircleXmark", good ? HEX.green : HEX.white), x: x + 0.2, y: y + 0.2, w: 0.42, h: 0.42, objectName: "servo-mark" + i, altText: good ? "works" : "broken" });
    text(s, name, { x: x + 0.2, y: y + 0.78, w: 1.6, h: 0.4, fontSize: 16, bold: true, color: good ? C.text1 : C.background1 });
  }
  card(s, 0.6, 5.15, 6.1, 1.25, "elbow-finding");
  text(s, [
    { text: "Elbow, torque on: ", options: { bold: true } },
    { text: "the 12 V supply drops to 11.3 V, the joint doesn't move, then the servo stops answering. The other five hold 11.7–12.0 V while moving.", options: { color: C.text2 } },
  ], { x: 0.85, y: 5.35, w: 5.6, h: 1.2, fontSize: 15 });
  const lessons = [
    ["FaRulerCombined", "Measure, don't trust the reply", "Every move is checked by reading the joint angles before and after."],
    ["FaVolumeHigh", "Say so when it can't move", "The black arm once said “yes” without moving; now it says out loud that it isn't ready."],
    ["FaScrewdriverWrench", "One part from working", "One new STS3215 servo (id 3), and the camera picking code is ready to run."],
  ];
  for (let i = 0; i < lessons.length; i++) {
    const y = 1.95 + i * 1.6;
    await badge(s, lessons[i][0], HEX.violet, 7.2, y, 0.75, "lesson" + i);
    text(s, lessons[i][1], { x: 8.2, y: y + 0.02, w: 4.5, h: 0.4, fontSize: 18, bold: true });
    text(s, lessons[i][2], { x: 8.2, y: y + 0.45, w: 4.5, h: 0.9, fontSize: 15, color: C.text2 });
  }
  s.addNotes("Why two arms? The white arm carries the wrist camera for picking objects; the black arm shows the interaction today. Its elbow servo failed during the hackathon, and we didn't guess: we measured it. Five joints move normally, and the elbow alone pulls the supply down and drops off the bus.");

  // ===== 12. Roadmap =====
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: "Next" });
  s.addText("Next: from gestures to fetching things", { placeholder: "title" });
  const road = [
    ["FaCamera", HEX.orange, "Hand me the pills", "New elbow servo, then the wrist camera finds the object and Claude plans the grab."],
    ["FaPills", HEX.teal, "Medication reminders", "Marco reminds on time, and the arm points to the right box."],
    ["FaBell", HEX.red, "“Help” palm gesture", "The Watcher's camera sees an open palm and alerts the family."],
    ["FaGlasses", HEX.violet, "Rokid glasses", "Caregivers see what the arm sees, and can guide it from anywhere."],
    ["FaWifi", HEX.ink, "No cable", "Marco drives the arm over Wi-Fi through its MCP access point (built, tested offline)."],
    ["FaRaspberryPi", HEX.green, "Off the laptop", "The whole brain on a small board next to the arm."],
  ];
  for (let i = 0; i < road.length; i++) {
    const col = i % 3, row = Math.floor(i / 3);
    const x = 0.6 + col * 4.1, y = 1.95 + row * 2.4;
    card(s, x, y, 3.85, 2.2, "road-card" + i);
    await badge(s, road[i][0], road[i][1], x + 0.3, y + 0.3, 0.75, "road-badge" + i);
    text(s, road[i][2], { x: x + 1.25, y: y + 0.45, w: 2.45, h: 0.5, fontSize: 18, bold: true });
    text(s, road[i][3], { x: x + 0.3, y: y + 1.2, w: 3.3, h: 0.9, fontSize: 14, color: C.text2 });
  }
  s.addNotes("What comes next: a new elbow servo turns on camera picking, so 'hand me the pills' really works. Then medication reminders, a palm gesture that alerts the family, Rokid glasses for caregivers, and no cable at all.");

  // ===== 13. Close =====
  s = pres.addSlide({ masterName: "TITLE_DARK", sectionTitle: "Next" });
  text(s, "AI COMPANION", { x: 0.8, y: 0.9, w: 7, h: 0.4, fontSize: 18, bold: true, color: ACC.orange, charSpacing: 4 });
  s.addText("Say it any way, and it does it, or tells you why not", { placeholder: "title" });
  text(s, "Claude decides; the safety layer enforces.", { x: 0.8, y: 4.4, w: 7.6, h: 0.5, fontSize: 22, italic: true, color: C.background2 });
  text(s, "Questions?", { x: 0.8, y: 5.4, w: 7, h: 0.6, fontSize: 28, bold: true, color: ACC.orange });
  text(s, "github.com/mehdi-loup/watcher-hub", { x: 0.8, y: 6.55, w: 8, h: 0.35, fontSize: 14, color: C.background2 });
  await badge(s, "FaHandHoldingHeart", HEX.orange, 8.9, 1.55, 3.6, "hero-close");
  s.addNotes([
    "Repeat in every answer: 'Say it any way, and it does it, or tells you why not.' and 'Claude decides; the safety layer enforces.'",
    "Why not a smart speaker? They have no hands. The value is the physical help: the arm acts.",
    "Is it safe? Low torque limits, a contact guard, a stop word that always wins, and Claude refuses anything unsafe. A small desk arm, not a mobile robot.",
    "Does it work offline? Speech recognition runs on the laptop; common commands work offline; free-form understanding needs the Claude API.",
    "Dialects? Cantonese is detected and answered in Cantonese; Claude also fixes misheard words.",
    "Why two arms? The white arm carries the camera for picking; its elbow servo failed during the hackathon, so the black arm runs the demo.",
  ].join("\n\n"));

  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", OUT);
}

build().catch((e) => { console.error(e); process.exit(1); });
