import json
import sys


def parse_netscape_cookie_file(path):
    cookies = {}

    with open(path, "r", encoding="utf-8") as cookie_file:
        for raw_line in cookie_file:
            line = raw_line.rstrip("\n")
            if not line:
                continue

            if line.startswith("#") and not line.startswith("#HttpOnly_"):
                continue

            if line.startswith("#HttpOnly_"):
                line = line[len("#HttpOnly_"):]

            if "\t" in line:
                parts = line.split("\t", 6)
            else:
                parts = line.split(None, 6)

            if len(parts) != 7:
                continue

            name = parts[5].strip()
            value = parts[6]
            if name:
                cookies[name] = value

    return cookies


def main():
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python cookies_txt_to_json.py input_cookie_txt output_json")

    input_path = sys.argv[1]
    output_path = sys.argv[2]
    cookies = parse_netscape_cookie_file(input_path)

    with open(output_path, "w", encoding="utf-8") as output_file:
        json.dump(cookies, output_file)
        output_file.write("\n")

    print(f"Wrote {len(cookies)} cookies to {output_path}")


if __name__ == "__main__":
    main()
