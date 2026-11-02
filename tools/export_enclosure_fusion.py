"""Exports the enclosure with its default settings to hardware/enclosure/export/, for releases. One set fits both
  builds: with PicoSocketHeight 8.5 (Pico in sockets) the base and lid come out byte-identical (checked 2026-11-02),
  because without the USB opening only the board model moves. Set EXTRA_SOCKETS_CHECK to export that set too, to check:
  base / lid (and the USB plug if the defaults ever include it) as 3MF and STL (print), as STEP (any CAD), and the whole design as .f3d (Fusion archive,
  timeline and user parameters included; newer Fusion versions open it). Built in a temporary design that is closed
  afterwards; the open design is not touched. Run through the Fusion MCP bridge or Fusion's Scripts dialog."""
import os, adsk.core, adsk.fusion
# The project folder from this file's place (tools/ -> ..). Through the Fusion MCP bridge the script arrives as text
# without __file__: the bridge adds it in front.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
D = os.path.join(ROOT, "hardware", "enclosure", "WattWindEnclosureV2")
OUT = os.path.join(ROOT, "hardware", "enclosure", "export")
PARTS = {"Bottom": "wattwind-base", "Top": "wattwind-lid", "USB plug": "wattwind-usb-plug"}
EXTRA_SOCKETS_CHECK = False
SETS = {"": 0.0, "pico-in-sockets-8.5mm-check": 8.5} if EXTRA_SOCKETS_CHECK else {"": 0.0}   # folder: PicoSocketHeight


def export_set(app, folder, socket_h):
    """One set in a temporary design: base / lid (/ USB plug) as STL, 3MF, STEP, and the design as .f3d."""
    out = []
    doc = app.documents.add(adsk.core.DocumentTypes.FusionDesignDocumentType)
    try:
        os.makedirs(folder, exist_ok=True)
        design = adsk.fusion.Design.cast(app.activeProduct)
        design.userParameters.add("PicoSocketHeight", adsk.core.ValueInput.createByString("%g mm" % socket_h), "mm", "")
        os.environ["WATTWIND_ENCLOSURE_DIR"] = D
        ns = {"__name__": "wattwind_enclosure"}
        exec(compile(open(os.path.join(D, "WattWindEnclosureV2.py"), encoding="utf-8").read(), "WattWindEnclosureV2.py", "exec"), ns)
        ns["build"]()
        design = adsk.fusion.Design.cast(app.activeProduct)
        em = design.exportManager
        for occ in design.rootComponent.occurrences:
            name = PARTS.get(occ.component.name)
            if not name:
                continue
            occ.isLightBulbOn = True
            body = occ.component.bRepBodies.item(0)
            bb = body.boundingBox
            out.append("%s: %.1f x %.1f x %.1f mm, %.2f cm3" % (name, (bb.maxPoint.x - bb.minPoint.x) * 10,
                       (bb.maxPoint.y - bb.minPoint.y) * 10, (bb.maxPoint.z - bb.minPoint.z) * 10, body.volume))
            o = em.createSTLExportOptions(body, os.path.join(folder, name + ".stl"))
            o.meshRefinement = adsk.fusion.MeshRefinementSettings.MeshRefinementHigh
            em.execute(o)
            try:
                em.execute(em.createC3MFExportOptions(body, os.path.join(folder, name + ".3mf")))
            except Exception as e:
                out.append("3mf skipped: %s" % e)
            em.execute(em.createSTEPExportOptions(os.path.join(folder, name + ".step"), occ.component))
        em.execute(em.createFusionArchiveExportOptions(os.path.join(folder, "wattwind-enclosure.f3d")))
    finally:
        doc.close(False)
    return out


def run(_context):
    app = adsk.core.Application.get(); user_doc = app.activeDocument
    try:
        for name, h in SETS.items():
            print("==", name, "(PicoSocketHeight %g mm)" % h)
            print(chr(10).join(export_set(app, os.path.join(OUT, name), h)))
    finally:
        if user_doc:
            user_doc.activate()
