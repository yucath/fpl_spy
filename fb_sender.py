from fb_manager import init_facebook
import requests
import time
import logging
import os

current_dir = os.path.dirname(os.path.realpath(__file__))

def read_txt(filepath):
    """Read message.txt preserving its structure (real newlines, emojis intact).

    Messenger's composer respects line breaks when we insert them as Shift+Enter,
    and the CDP-based typing path in FacebookManager handles non-BMP Unicode
    (full emoji set). So we no longer need to collapse newlines into separators.
    Trailing whitespace on each line is stripped, and runs of more than one
    blank line are collapsed to a single blank line for tidiness.
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            raw_lines = [line.rstrip() for line in f.read().splitlines()]

        cleaned = []
        prev_blank = False
        for line in raw_lines:
            if not line:
                if prev_blank:
                    continue
                prev_blank = True
            else:
                prev_blank = False
            cleaned.append(line)

        while cleaned and not cleaned[0]:
            cleaned.pop(0)
        while cleaned and not cleaned[-1]:
            cleaned.pop()

        return "\n".join(cleaned)
    except Exception as e:
        print(f"Error reading file: {e}")
        return None


def send_message(thread_id):
    """Send message to a Facebook thread"""
    fb = init_facebook()
    if not fb:
        print("Failed to initialize Facebook manager")
        return False
    
    try:
        # Read the message and ensure it's a single string
        message_txt = read_txt(os.path.join(current_dir, 'message.txt'))
        if not message_txt:
            print("No message content found")
            return False

        # Find PDF file
        file_paths = os.listdir(os.path.join(current_dir, 'plots'))
        pdf_files = [f for f in file_paths if f.endswith('.pdf')]
        if not pdf_files:
            print("No PDF file found")
            return False
            
        pdf_file = pdf_files[0]
        pdf_path = os.path.join(current_dir, 'plots', pdf_file)

        # Send as a single message with attachment
        success = fb.send_message(
            thread_id=thread_id,
            message=message_txt,
            file_path=pdf_path
        )
        return success
    except Exception as e:
        print(f"Error sending message: {e}")
        return False
    finally:
        fb.close()

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Send messages to Facebook thread')
    parser.add_argument('--thread', type=str, required=False, help='Facebook thread ID')
    args = parser.parse_args()
    args.thread = os.getenv('FANTASY_GROUP_ID')
    
    # Setup logging
    local_dir = os.path.dirname(os.path.realpath(__file__))
    logfile = os.path.join(local_dir, 'fb_messenger.log')
    logging.basicConfig(
        filename=logfile,
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    try:
        success = send_message(args.thread)
        if success:
            print("Successfully sent message")
            logging.info("Successfully sent message")
        else:
            print("Failed to send message")
            logging.error("Failed to send message")
    except Exception as e:
        print(f"Unexpected error: {e}")
        logging.error(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()