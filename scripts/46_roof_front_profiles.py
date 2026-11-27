"""Front-to-back roof profiles of flat-roofed rows, by neighborhood
(investigation only; draws nothing).

Why: scripts/45_roof_forms.py measures pitch well, but the shingled slope
across the front of many interwar and postwar Northeast rows (seen in dated
Evening Bulletin photos; docs/building_age_styles.md) is only about one
0.5 m LiDAR cell deep, so a per-building test is noisy. Averaging thousands
of houses shows whether a neighborhood's rows have it.

For each group (a neighborhood and OPA style codes), up to 4,000 footprints
that 45_roof_forms.py classed "flat" are taken (rerun 45 for the areas
first). For each, with the street-facing side from facades.front_dirs, the
DSM (data/processed/<area>_lidar_grid.npz) is binned by distance from the
front wall in 0.25 m steps, over the footprint shrunk 0.5 m (off the party
walls), relative to the median of the band 3-6 m back. Reported: the median
profile, and per building "dip" (the lowest of the 0.5-1.0 m bins at least
0.3 m below the roof behind) and "raised" (at least 0.1 m above it). Bins
under 0.5 m are empty after the shrink.

Writes output/building_age/roof_front_profiles.json.
Usage: uv run python scripts/46_roof_front_profiles.py
"""
import json, csv, importlib.util
import numpy as np
import shapely
from shapely.geometry import shape, LineString
from shapely import STRtree
from rasterio.features import geometry_mask
from rasterio.transform import Affine
spec=importlib.util.spec_from_file_location('rf','scripts/45_roof_forms.py'); rf=importlib.util.module_from_spec(spec); spec.loader.exec_module(rf)
from pixelphilly import facades
from pixelphilly.projection import load_config, local_frame
# {label: [area, neighborhood LISTNAME, [OPA building_code_description_new]]}
GROUPS = {"Mayfair postwar rows":["lower_northeast","Mayfair",["ROW POST WAR"]],
 "Oxford Circle postwar rows":["lower_northeast","Oxford Circle",["ROW POST WAR"]],
 "Rhawnhurst postwar twins":["lower_northeast","Rhawnhurst",["TWIN POST WAR"]],
 "Morrell Park postwar rows":["upper_northeast","Morrell Park",["ROW POST WAR"]],
 "Parkwood Manor postwar rows":["upper_northeast","Parkwood Manor",["ROW POST WAR"]],
 "Olney porch rows":["upper_north_lidar","Olney",["ROW PORCH FRONT"]],
 "Cobbs Creek porch rows":["west_lidar","Cobbs Creek",["ROW PORCH FRONT"]],
 "Mayfair porch rows":["lower_northeast","Mayfair",["ROW PORCH FRONT"]],
 "Lower Moyamensing rows":["south_lidar","Lower Moyamensing",["ROW TYPICAL"]],
 "Point Breeze rows":["south_lidar","Point Breeze",["ROW TYPICAL"]],
 "Strawberry Mansion rows":["north_lidar","Strawberry Mansion",["ROW TYPICAL"]]}
hoods = GROUPS
nb={f['properties']['LISTNAME']:shape(f['geometry']) for f in json.load(open('data/raw/philadelphia-neighborhoods.geojson'))['features']}
BINS=np.arange(0,7.01,0.25)
out={}
for label,(area,hood,styles) in hoods.items():
    rows={r['objectid']:r for r in csv.DictReader(open(f'output/building_age/roof_forms_{area}.csv')) if r['opa_style'] in styles and r['cls']=='flat'}
    cfg=load_config(area); fr=local_frame(cfg); dsm,gnd,origin,_=rf.load_grid(area)
    tl=lambda g: shapely.transform(g, lambda xy: np.column_stack(fr.to_local(xy[:,0],xy[:,1])))
    poly=nb[hood]
    fps=[(str(f['properties']['objectid']),shape(f['geometry'])) for f in json.load(open(f'data/raw/{area}_buildings.geojson'))['features'] if f.get('geometry') and str(f['properties']['objectid']) in rows]
    fps=[(o,g) for o,g in fps if poly.contains(g.representative_point())]
    st=[tl(shape(f['geometry'])) for f in json.load(open(f'data/raw/{area}_streets.geojson'))['features'] if f.get('geometry')]
    tree=STRtree(st)
    profs=[]
    for oid,g in fps[:4000]:
        g=tl(g).buffer(0)
        if g.geom_type!='Polygon': continue
        fd=facades.front_dirs(g,[st[j] for j in tree.query(g.buffer(30))])
        if not fd: continue
        d=np.array(fd[0]); minx,miny,maxx,maxy=g.bounds
        c0=int((minx-origin[0])/.5)-2; c1=int((maxx-origin[0])/.5)+3; r0=int((origin[1]-maxy)/.5)-2; r1=int((origin[1]-miny)/.5)+3
        if min(c0,r0)<0 or c1>dsm.shape[1] or r1>dsm.shape[0]: continue
        win=dsm[r0:r1,c0:c1].astype(float)
        tf=Affine(.5,0,origin[0]+c0*.5,0,-.5,origin[1]-r0*.5)
        m=geometry_mask([g.buffer(-0.5)],out_shape=win.shape,transform=tf,invert=True)  # keep off the party walls
        rr,cc=np.indices(win.shape); e=origin[0]+(c0+cc+.5)*.5; n=origin[1]-(r0+rr+.5)*.5
        s=e*d[0]+n*d[1]; xs,ys=g.exterior.coords.xy; dist=max(x*d[0]+y*d[1] for x,y in zip(xs,ys))-s
        back=m&(dist>=3)&(dist<=6)
        if back.sum()<4: continue
        ref=np.nanmedian(win[back]); p=[]
        for a,b in zip(BINS[:-1],BINS[1:]):
            sel=m&(dist>=a)&(dist<b); p.append(np.nanmedian(win[sel])-ref if sel.sum() else np.nan)
        profs.append(p)
    P=np.array(profs); med=np.nanmedian(P,0); q25=np.nanpercentile(P,25,0)
    first=np.nanmin(P[:,2:4],1)
    dip=float(np.mean(first<=-0.3)); rise=float(np.mean(first>=0.1))
    out[label]={'dip_share':round(dip,3),'raised_share':round(rise,3),'n':len(profs),'median':[round(float(v),2) for v in med],'q25':[round(float(v),2) for v in q25]}
    print(label,len(profs),'dip',round(dip,3),'raised',round(rise,3),' '.join(f"{v:+.2f}" for v in med[:12]))
print('bins m from front:',' '.join(f"{v:.2f}" for v in BINS[:12]))
json.dump({'bins':BINS.tolist(),**out},open('output/building_age/roof_front_profiles.json','w'),indent=1)
