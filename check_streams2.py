import pypdf, os

for name in ['Lab Abstract Report Detailed.pdf', 'Current occupancy list (companywise).pdf', 'Prescription Details.pdf']:
    path = os.path.join(r'd:\SMRFT\Projects\HMS', name)
    reader = pypdf.PdfReader(path)
    p = reader.pages[0]
    print(f"=== {name} ===")
    c = p.get('/Contents')
    print("Contents type:", type(c))
    if isinstance(c, list):
        for item in c:
            print("item:", len(item.get_data()), repr(item.get_data()[:100]))
    elif hasattr(c, 'get_data'):
        print("data len:", len(c.get_data()))
        print("data sample:", repr(c.get_data()[:300]))
    else:
        print("c:", c)

