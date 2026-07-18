import sys
from pathlib import Path
from library import list_documents

# Add current dir to path so we can import library
sys.path.append(str(Path(__file__).parent))

def test_library():
    try:
        print("Testing list_documents for 'concepts'...")
        docs = list_documents("concepts")
        if docs:
            print(f"Success: Found {len(docs)} documents in 'concepts'.")
            for d in docs[:3]:
                print(f" - {d['name']}")
        else:
            print("Failure: No documents found in 'concepts'.")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_library()
