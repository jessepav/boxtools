import logging

# Prevent the Box SDK from spewing logging messages
logging.getLogger('boxsdk').setLevel(logging.CRITICAL)

def getuserinfo(client):
    return client.user().get()

def list_folder(client, folder_id, fields=['id', 'type', 'name']):
    folder = client.folder(folder_id=folder_id)
    return folder.get(), list(folder.get_items(fields=fields))

def search(client, **kwargs):
    results = client.search().query(**kwargs)
    # We can't just throw the iterator returned by query() into a list(), because it stalls,
    # so we need to manually retrieve 'limit' items
    limit = kwargs.get('limit', 10)
    items = []
    for i, item in enumerate(results, start=1):
        items.append(item)
        if i == limit:
            break
    return items
