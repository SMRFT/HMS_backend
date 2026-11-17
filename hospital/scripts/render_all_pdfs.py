import fitz, os

pdf_files = [
    r'd:\SMRFT\Projects\HMS\ADVANCE.pdf',
    r'd:\SMRFT\Projects\HMS\Advance Registration Report.pdf',
    r'd:\SMRFT\Projects\HMS\Bill Wise Detailed Report.pdf',
    r'd:\SMRFT\Projects\HMS\Shift Basis Collection Report.pdf',
    r'd:\SMRFT\Projects\HMS\Credit Card & Electronic Payment Report(OP).pdf',
    r'd:\SMRFT\Projects\HMS\Date-Wise Collection Summary.pdf',
    r'd:\SMRFT\Projects\HMS\Credit Card & Electronic Payment Report.pdf'
]

out_dir = r'C:\Users\Msi\.gemini\antigravity\brain\cd655ff6-1b77-4588-8443-2f1c9bebc455'

for p in pdf_files:
    doc = fitz.open(p)
    name = os.path.basename(p).replace('.pdf', '').replace(' ', '_').replace('&', 'and').replace('(', '_').replace(')', '_')
    for i in range(len(doc)):
        page = doc[i]
        pix = page.get_pixmap(dpi=150)
        img_path = os.path.join(out_dir, f"{name}_page_{i+1}.png")
        pix.save(img_path)
        print(f"Saved {img_path} ({pix.width}x{pix.height})")

