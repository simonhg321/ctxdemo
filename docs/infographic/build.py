#!/usr/bin/env python3
"""Render docs/infographic/see-it-think.html to PDF + PNG, twice: the Gonzaga original and an NFCU edition (rented GPU, no layers
sidecar). PDFs land in static/peek/ so wall.html's "this wall" card can link them (CTXDEMO_INFOGRAPHIC picks the edition)."""
import pathlib, subprocess, shutil, tempfile
HERE = pathlib.Path(__file__).resolve().parent; PEEK = HERE.parent.parent / "static" / "peek"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SRC = (HERE / "see-it-think.html").read_text()
NFCU = [  # (Gonzaga text, NFCU text) — every pair must match exactly once
  ('IIAT HACLab<small>Gonzaga University · September 2026</small>', 'NFCU · ACI all-hands<small>from the IIAT HACLab, Gonzaga University · September 2026</small>'),
  ('Everything on the wall runs here, in the lab, on one graphics card. Nothing leaves the building.', 'Everything on this wall runs on one rented graphics card in Seattle. Questions are logged; first names are optional.'),
  ('<b>NVIDIA L40</b><small>one GPU · 46 GB memory</small>', '<b>RTX 4000 Ada</b><small>one GPU · 20 GB memory</small>'),
  ('<b>~30 / s</b><small>tokens generated per second</small>', '<b>~35 / s</b><small>tokens generated per second, one person at a time</small>'),
  ('<div class="mem"><i class="a"></i><i class="b2"></i></div>', '<div class="mem"><i class="a" style="width:41%"></i><i class="b2" style="width:45%"></i></div>'),
  ('<span>■ 18 GB the model you talk to</span><span style="color:var(--red)">■ 10 GB its 4B sibling, read layer by layer</span><span>□ 18 GB free</span>', '<span>■ 8 GB the model you talk to</span><span style="color:var(--red)">■ 9 GB working memory for 15 people at once</span><span>□ 3 GB spare</span>'),
  ('<p>A smaller sibling of the model (Qwen3 4B, 36 layers) reads the same question', '<p>On the lab wall at Gonzaga, a smaller sibling of the model (Qwen3 4B, 36 layers) reads the same question'),
  ('<span class="url">iiat.gonzaga.edu/demo</span>', '<span class="url">demo.instockornot.club</span>'),
  ('Built in the IIAT HACLab on IIAT-HACLAB-01 · vLLM · TransformerLens · one L40', 'Built in the IIAT HACLab at Gonzaga University · vLLM · one rented RTX 4000 Ada'),
]
def render(html: str, stem: str):
    with tempfile.TemporaryDirectory() as td:
        page = pathlib.Path(td) / "page.html"; page.write_text(html)
        base = [CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=4000", "--hide-scrollbars"]
        subprocess.run(base + [f"--print-to-pdf={HERE / (stem + '.pdf')}", page.as_uri()], check=True, capture_output=True)
        subprocess.run(base + ["--window-size=1056,1632", f"--screenshot={HERE / (stem + '.png')}", page.as_uri()], check=True, capture_output=True)
    shutil.copy(HERE / (stem + ".pdf"), PEEK / (stem + ".pdf")); print("rendered", stem)
render(SRC, "see-it-think")
nf = SRC
for a, b in NFCU:
    assert nf.count(a) == 1, a[:60]; nf = nf.replace(a, b)
(HERE / "see-it-think-nfcu.html").write_text(nf)
render(nf, "see-it-think-nfcu")
