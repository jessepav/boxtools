import logging

# Prevent the Box SDK from spewing logging messages
logging.getLogger('boxsdk').setLevel(logging.CRITICAL)

def getuserinfo(client):
    return client.user().get()
