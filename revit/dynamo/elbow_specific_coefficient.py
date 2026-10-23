# -*- coding: utf-8 -*-
# Dynamo Python Script node (IronPython 2.7 veya CPython3)
#
# Secilen havalandirma sistemindeki dirseklerin (Duct Fitting, Part Type = Elbow)
# Loss Method'unu "Specific Coefficient" yapar ve zeta degerini girer.
# zeta = zeta90(r/W) x K(aci)  -- Idelchik / ASHRAE CR3-1 yaklasik degerleri
#
# Girisler:
#   IN[0]  SYSTEM_NAME  (string)  varsayilan "К1-С1-ЛК-ПД2"
#   IN[1]  R_W          (number)  dirsek ic radyus / genislik orani, 0 = keskin koseli
#   IN[2]  VANES        (bool)    yonlendirici kanat var mi (sadece r/W = 0 icin)
#   IN[3]  APPLY        (bool)    False = sadece rapor, True = modele yaz
#
# Cikis: her dirsek icin rapor satirlari (Id, aci, zeta, debi, Pressure Drop)

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitServices")
from System import Double
from Autodesk.Revit.DB import (FilteredElementCollector, BuiltInParameter,
                               BuiltInCategory, FamilyInstance, Domain)
from Autodesk.Revit.DB.Mechanical import MechanicalSystem
from Autodesk.Revit.DB.ExtensibleStorage import Entity
from Autodesk.Revit.DB.ExternalService import (ExternalServiceRegistry,
                                               ExternalServices)
import Autodesk.Revit.DB.Mechanical as Mech
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

doc = DocumentManager.Instance.CurrentDBDocument


def _in(i, default):
    try:
        v = IN[i]
        return default if v is None else v
    except Exception:
        return default


SYSTEM_NAME = _in(0, u"К1-С1-ЛК-ПД2")
R_W = float(_in(1, 0.0))
VANES = bool(_in(2, False))
APPLY = bool(_in(3, False))

# --- zeta tablolari -------------------------------------------------------
# 90 derece dikdortgen dirsek, kanatsiz, H/W ~ 1-1.5: (r/W, zeta90)
# ASHRAE CR3-1 / Idelchik B1 = 0.21/(r/W)^2.5 (r/W<1), 0.21/sqrt(r/W) (r/W>=1)
ZETA90 = [(0.0, 1.20), (0.5, 1.10), (0.75, 0.42), (1.0, 0.21),
          (1.5, 0.16), (2.0, 0.15)]
ZETA90_VANES = 0.30
# Aci duzeltme katsayisi K(aci): (derece, K)
ANGLE_K = [(0, 0.0), (30, 0.45), (45, 0.60), (60, 0.78), (75, 0.90),
           (90, 1.00), (110, 1.13), (130, 1.20), (150, 1.28), (180, 1.40)]


def interp(table, x):
    if x <= table[0][0]:
        return table[0][1]
    for (x0, y0), (x1, y1) in zip(table, table[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return table[-1][1]


def zeta_for(angle_deg):
    z90 = ZETA90_VANES if (VANES and R_W == 0) else interp(ZETA90, R_W)
    return round(z90 * interp(ANGLE_K, angle_deg), 3)


# --- yardimcilar ----------------------------------------------------------
# Kiril / Latin benzer harfleri esitle (K1-C1 / К1-С1 karisikligi icin)
_LOOK = {u"К": u"K", u"С": u"C", u"Р": u"P", u"А": u"A", u"Е": u"E",
         u"О": u"O", u"Н": u"H", u"М": u"M", u"Т": u"T", u"Х": u"X",
         u"В": u"B"}


def norm(s):
    s = (s or u"").strip().upper()
    return u"".join(_LOOK.get(ch, ch) for ch in s)


def eid(i):
    # Revit 2024+ : ElementId.Value, eski surumler: IntegerValue
    return i.Value if hasattr(i, "Value") else i.IntegerValue


def connectors(el):
    return [c for c in el.MEPModel.ConnectorManager.Connectors
            if c.Domain == Domain.DomainHvac]


def bend_angle(el):
    cs = connectors(el)
    if len(cs) != 2:
        return None
    a = cs[0].CoordinateSystem.BasisZ.AngleTo(cs[1].CoordinateSystem.BasisZ)
    return round(180.0 - a * 180.0 / 3.141592653589793, 1)


def flow_m3h(el):
    try:
        return round(max(c.Flow for c in connectors(el)) * 101.9406, 0)
    except Exception:
        return None


def pdrop(el):
    p = el.get_Parameter(BuiltInParameter.RBS_PRESSURE_DROP)
    return p.AsValueString() if p else None


def specific_coefficient_server():
    svc = ExternalServiceRegistry.GetService(
        ExternalServices.BuiltInExternalServices.DuctFittingAndAccessoryPressureDropService)
    for sid in svc.GetRegisteredServerIds():
        srv = svc.GetServer(sid)
        name = srv.GetName()
        low = name.lower()
        if "ashrae" in low:
            continue
        if "coefficient" in low or u"коэффициент" in low:
            try:
                srv = Mech.IDuctFittingAndAccessoryPressureDropServer(srv)
            except Exception:
                pass
            return sid, srv, name
    return None, None, None


# --- sistemi bul ----------------------------------------------------------
report = []
target = norm(SYSTEM_NAME)
systems = [s for s in FilteredElementCollector(doc).OfClass(MechanicalSystem)
           if norm(s.Name) == target]

if not systems:
    OUT = [u"HATA: sistem bulunamadi: " + SYSTEM_NAME]
else:
    system = systems[0]
    stype = doc.GetElement(system.GetTypeId())
    report.append(u"Sistem: %s | Tip: %s | Calculations: %s" % (
        system.Name, stype.Name if stype else u"?",
        getattr(stype, "CalculationLevel", u"?")))

    elbows = []
    for el in system.DuctNetwork:
        if not isinstance(el, FamilyInstance) or el.Category is None:
            continue
        if eid(el.Category.Id) != int(BuiltInCategory.OST_DuctFitting):
            continue
        if str(el.MEPModel.PartType) == "Elbow":
            elbows.append(el)
    report.append(u"Bulunan dirsek sayisi: %d" % len(elbows))

    sid, srv, srv_name = specific_coefficient_server()
    if sid is None:
        report.append(u"HATA: 'Specific Coefficient' sunucusu bulunamadi")
    else:
        schema = srv.GetDataSchema()
        field = None
        for f in schema.ListFields():
            if f.ValueType == Double:
                field = f
                break
        report.append(u"Loss Method sunucusu: %s | alan: %s" % (
            srv_name, field.FieldName if field else u"YOK"))

        if APPLY and field is not None:
            TransactionManager.Instance.EnsureInTransaction(doc)
            for el in elbows:
                ang = bend_angle(el) or 90.0
                z = zeta_for(ang)
                el.get_Parameter(
                    BuiltInParameter.RBS_DUCT_FITTING_LOSS_METHOD_SERVER_PARAM
                ).Set(sid.ToString())
                ent = Entity(schema)
                ent.Set[Double](field, Double(z))
                el.SetEntity(ent)
            doc.Regenerate()
            TransactionManager.Instance.TransactionTaskDone()

        for el in elbows:
            ang = bend_angle(el)
            report.append(u"Id %s | aci %s | r/W %s | zeta %s | debi %s m3/h | dP %s" % (
                eid(el.Id), ang, R_W, zeta_for(ang or 90.0),
                flow_m3h(el), pdrop(el)))

    OUT = report
