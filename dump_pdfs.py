import pypdf, os

pdf_files = [
    'PATIENT WISE PHARMACY IP BILL DETAILED.pdf',
    'Lab Abstract Report Detailed.pdf',
    'Current occupancy list (companywise).pdf',
    'Insurance Bills Status.pdf',
    'Insurance Bills Status(Report Branch Wise) Dues.pdf',
    'Company wise registration.pdf',
    'Insurance Discharge Bill (All).pdf',
    'Prescription Details.pdf'
]

for name in pdf_files:
    path = os.path.join(r'd:\SMRFT\Projects\HMS', name)
    reader = pypdf.PdfReader(path)
    print(f'======================================================================')
    print(f'=== {name} (Pages: {len(reader.pages)}) ===')
    print(f'======================================================================')
    for page_idx, page in enumerate(reader.pages):
        text = page.extract_text()
        print(f'--- Page {page_idx+1} ---')
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        for line in lines:
            print(line)
        print()

