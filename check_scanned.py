import pypdf, os

for name in ['Lab Abstract Report Detailed.pdf', 'Current occupancy list (companywise).pdf', 'Prescription Details.pdf']:
    path = os.path.join(r'd:\SMRFT\Projects\HMS', name)
    reader = pypdf.PdfReader(path)
    print(name, 'pages:', len(reader.pages))
    page0 = reader.pages[0]
    print('images in page 0:', len(page0.images))
    print('text len:', len(page0.extract_text()))
    for img in page0.images:
        print(' - image name:', img.name)

