import pypdf, os

for name in ['Lab Abstract Report Detailed.pdf', 'Current occupancy list (companywise).pdf', 'Prescription Details.pdf']:
    path = os.path.join(r'd:\SMRFT\Projects\HMS', name)
    reader = pypdf.PdfReader(path)
    p = reader.pages[0]
    print(f"=== {name} ===")
    print("Keys in page:", p.keys())
    if '/Resources' in p:
        res = p['/Resources']
        print("Resources keys:", res.keys() if hasattr(res, 'keys') else res)
        if '/Font' in res:
            print("Fonts:", res['/Font'].keys())
        if '/XObject' in res:
            print("XObjects:", res['/XObject'].keys())
    # raw content
    contents = p.get_contents()
    if contents:
        data = contents.get_data()
        print("Raw content len:", len(data))
        print("Raw content sample:", repr(data[:300]))

