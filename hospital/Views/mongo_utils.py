"""
Helper utility to convert MongoDB documents to JSON serializable format
"""

def serialize_mongo_doc(doc):
    """Convert a single MongoDB document to JSON serializable format"""
    if doc and '_id' in doc:
        doc['id'] = str(doc['_id'])
        del doc['_id']
    return doc

def serialize_mongo_docs(docs):
    """Convert list of MongoDB documents to JSON serializable format"""
    result = []
    for doc in docs:
        if '_id' in doc:
            doc['id'] = str(doc['_id'])
            del doc['_id']
        result.append(doc)
    return result
