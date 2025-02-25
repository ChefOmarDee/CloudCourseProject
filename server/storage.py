# from google.cloud import datastore, storage
from google.cloud import storage

import time

# datastore_client = datastore.Client()
storage_client = storage.Client()

###
# Datastore examples
# ###
# def list_db_entries():
#     query = datastore_client.query(kind="photos")

#     for photo in query.fetch():
#         print(photo.items())

# def add_db_entry(object):
#     entity = datastore.Entity(key=datastore_client.key('photos'))
#     entity.update(object)

#     datastore_client.put(entity)


# def fetch_db_entry(object):
#     #print(object)

#     query = datastore_client.query(kind='photos')

#     for attr in object.keys():
#         query.add_filter(attr, "=", object[attr])

#     obj = list(query.fetch())

#     #print("fetch")
#     #for photo in obj:
#     #    print(photo.items())

#     return obj

###
# Cloud Storage examples
###
def get_list_of_files(bucket_name):
    """Lists all the blobs in the bucket."""
    print("\n")
    print("get_list_of_files: "+bucket_name)

    blobs = storage_client.list_blobs(bucket_name)
    print(blobs)
    files = []
    for blob in blobs:
        files.append(blob.name)

    return files

def upload_file(bucket_name, file_name):
    """Send file to bucket."""
    print("\n")
    print("upload_file: "+bucket_name+"/"+file_name)

    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(file_name)

    blob.upload_from_filename(file_name)

    return 

def download_file(bucket_name, file_name):
    """ Retrieve an object from a bucket and saves locally"""  
    print("\n")
    print("download_file: "+bucket_name+"/"+file_name)
    bucket = storage_client.bucket(bucket_name)

    blob = bucket.blob(file_name)
    blob.download_to_filename(file_name)
    blob.reload()
    print(f"Blob: {blob.name}")
    print(f"Bucket: {blob.bucket.name}")
    print(f"Storage class: {blob.storage_class}")
    print(f"Size: {blob.size} bytes")
    print(f"Content-type: {blob.content_type}")
    print(f"Public URL: {blob.public_url}")

    return

# print(get_list_of_files("de-andrade-fau"))

# upload_file("de-andrade-fau", "test.txt")
# print(get_list_of_files("de-andrade-fau"))

# download_file("de-andrade-fau", "test.txt")
# upload_file("de-andrade-fau", "test1.txt")
# download_file("de-andrade-fau", "test1.txt")
# print(get_list_of_files("de-andrade-fau"))

# download_file("de-andrade-fau", "sample_640Ã—426.jpeg")


###
# Datastore
###
list_db_entries()

obj = {"name":"fau-rocks.jpeg", "url":"blablabla.com/ricardo.jpeg", "user":"rdeandrade", 'timestamp':int(time.time())}
add_db_entry(obj)

obj1 = {'user':'rdeandrade'}
print(obj1)
result=fetch_db_entry(obj1)
print(result)
print(len(result))