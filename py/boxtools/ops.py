import logging

# Prevent the Box SDK from spewing logging messages
logging.getLogger('boxsdk').setLevel(logging.CRITICAL)

def getuserinfo(client):
    return client.user().get()

def list_folder(client, folder_id, fields=['id', 'type', 'name']):
    folder = client.folder(folder_id=folder_id)
    return folder.get(), folder.get_items(fields=fields)
