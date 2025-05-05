from bsky_utils import *
import fitz
import sys


def print_pdf_metadata(path):
    doc = fitz.open(path)
    metadata = doc.metadata
    for key, value in metadata.items():
        print(f"{key}: {value}")

def create_book_record(session, service, path):
    record = create_book_metadata(path)

    # verify_mode = False
    # if verify_mode:
    record = verify_book_metadata(record)

    # thumb_mode = False
    # if thumb_mode:
    #     record = add_thumbnail(record, path)
    
    # desc_mode = False
    # if desc_mode:
    #     record = add_description(record, path)

    record['$type'] = 'dev.dreary.library.book'
    record['file'] = upload_blob(session, service, path)
    record['createdAt'] = generate_timestamp()

    return record

def create_one_book(session, service, path):
    record = create_book_record(session, service, path)
    return create_record(session, service, record)

def create_book_metadata(path):
    if not path.endswith('.pdf'):
        return {
            "title": None,
            "authors": []
        }
    
    doc = fitz.open(path)
    metadata = doc.metadata
    authors = metadata.get('author')
    title = metadata.get('title')
    return {
        "title": title.title() if title else "",
        "authors": [val.strip().title() for val in authors.split(",")] if authors else [],
        "pageCount": len(doc)
    }

def verify_book_metadata(record):
    HIGHLIGHT = "\033[96m"
    RESET = "\033[0m"

    while True:
        print("\n--- Metadata ---")
        keys = list(record.keys())
        for i, key in enumerate(keys, 1):
            value = record[key]
            if key in ["title", "authors"] and not value:
                print(f"{i}) {HIGHLIGHT}{key}{RESET}: {value}")
            else:
                if isinstance(value, list):
                    print(f"{i}) {key}: {', '.join(value)}")
                else:
                    print(f"{i}) {key}: {value}")

        print("\nEnter the number of a field to edit, or press Enter to continue.")
        choice = input("Edit field #: ").strip()

        if choice == "+":
            new_field = input(f"Enter new field: ")
            if not new_field: continue
            new_value = input(f"Enter new value for '{new_field}': ")
            record[new_field] = new_value
            continue

        if not choice:
            if not record.get("title") or not record.get("authors"):
                print(f"{HIGHLIGHT}Please enter values for required fields (title and authors).{RESET}")
                continue
            break

        if not choice.isdigit() or not (1 <= int(choice) <= len(keys)):
            print(f"{HIGHLIGHT}Invalid selection. Try again.{RESET}")
            continue

        field = keys[int(choice) - 1]
        new_value = input(f"Enter new value for '{field}': ")
        if isinstance(record[field], list):
            record[field] = [val.strip() for val in new_value.split(",")]
        else:
            record[field] = new_value.strip()

    print()
    return record

def add_book_thumbnail(record, path):
    return record

def add_book_description(record, path):
    return record

def select_shelf_uri(session, service, shelves):
    if not shelves:
        print("No shelves yet.")
        if input("Create new shelf?").upper() in ["Y", "YES"]:
            return create_shelf(session, service)
        return None

    while True:
        for i, shelf in enumerate(shelves, 1):
            print(f"{i}) {traverse(shelf, ['value', 'name'])}")
        
        print()
        choice = input("Shelf #: ").strip()

        if not choice:
            print(f"No option selected. Quitting.")
            return None

        if not choice.isdigit() or not (1 <= int(choice) <= len(shelves)):
            print(f"Invalid selection. Try again.")
            continue

        return shelves[int(choice) - 1].get('uri')

def select_book_uri(books):
    if not books:
        print("No books yet. Quitting.")
        return None

    decorated = []
    for book in books:
        label = f"{", ".join(traverse(book, ['value', 'authors']))} - {traverse(book, ['value', 'title'])}"
        decorated.append((label, book))

    decorated.sort(key=lambda x: x[0])

    for i, (label, _) in enumerate(decorated, 1):
        print(f"{i}) {label}")

    print()
    choice = input("Comma-delimited book #s: ").strip()

    if not choice:
        print("No option selected. Quitting.")
        return None

    print("\nSelected:")
    book_uris = []

    for i in choice.split(','):
        i = i.strip()
        if not i.isdigit() or not (1 <= int(i) <= len(decorated)):
            continue
        label, book = decorated[int(i) - 1]
        book_uris.append(book.get('uri'))
        print(label)

    return book_uris

def add_books_to_shelf(session, service):
    shelves = list_records(session.get('did'), service, 'dev.dreary.library.shelf')
    shelf_uri = select_shelf_uri(session, service, shelves)
    if not shelf_uri: return

    books = list_records(session.get('did'), service, 'dev.dreary.library.book')
    book_uris = select_book_uri(books)
    if not book_uris: return

    apply_writes_create(session, service, [
        {
            "$type": 'dev.dreary.library.shelfitem',
            "book": book_uri,
            "shelf": shelf_uri,
            "createdAt": generate_timestamp()
        }
        for book_uri in book_uris
    ])
    print("Book(s) added to shelf successfully.")

def create_shelf(session, service):
    print("\nEnter shelf data.")
    record = {
        "$type": 'dev.dreary.library.shelf',
        "name": input("Name: "),
        "createdAt": generate_timestamp(),
        "description": input("Description: ")
    }
    if icon_path := input("Icon file path: "):
        record['icon'] = upload_blob(session, service, icon_path)
    print()
    return create_record(session, service, record)

def main():
    with open('../../config.json') as f:
        config = json.load(f)
    HANDLE = config.get('HANDLE')
    PASSWORD = config.get('PASSWORD')
    if not (HANDLE and PASSWORD):
        print('Enter credentials in config.json')
        return
    
    did = resolve_handle(HANDLE)
    service = get_service_endpoint(did)
    session = get_session(did, PASSWORD, service)

    if len(sys.argv) >= 2:
        return create_one_book(session, service, sys.argv[1])

    while True:
        print()
        print("1) Create Book")
        print("2) Create Shelf")
        print("3) Add Book to Shelf")
        print()

        choice = input("Select mode #: ").strip()

        if not choice:
            return

        if not choice.isdigit() or not (1 <= int(choice) <= 3):
            print(f"Invalid selection. Try again.\n")
            continue

        if choice == "1":
            path = input('Input book file path: ')
            if not path: return
            return create_one_book(session, service, path)
        elif choice == "2":
            return create_shelf(session, service)
        elif choice == "3":
            return add_books_to_shelf(session, service)
        

if __name__ == "__main__":
    main()