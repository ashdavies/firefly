import argparse
import itertools
import locale
import logging
import os
import pandas as pd
import pdfminer.high_level
import pdfminer.layout
import typing

from datetime import datetime

locale.setlocale(locale.LC_ALL, 'de_DE')

logging.getLogger().setLevel(logging.INFO)
logging.basicConfig(format="%(message)s")

pd.set_option("display.max_columns", None)
pd.set_option("display.max_rows", None)
pd.set_option("display.width", 1000)
pd.options.mode.chained_assignment = None


def is_date(value: str) -> bool:
    try:
        return bool(datetime.strptime(value, "%d.%m.%y"))
    except ValueError:
        return False


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--transaction-date", default="Datum Beleg")
    parser.add_argument("--booking-date", default="Datum Buchung")
    parser.add_argument("--description", default="Angabe des Unternehmens / Verwendungszweck")
    parser.add_argument("--currency", default="Währung")
    parser.add_argument("--original-amount", default="Betrag")
    parser.add_argument("--exchange-rate", default="Kurs")
    parser.add_argument("--amount", default="Betrag in EUR")
    return parser.parse_args()


def has_amounts(iterator, expected: int) -> bool:
    return expected == len([it for it in iterator[-expected:] if it == "+" or it == "-"])


args = parse_args()
df = pd.DataFrame(columns=[args.transaction_date, args.booking_date, args.description, args.currency,
                           args.original_amount, args.exchange_rate, args.amount])

# Iterate over files in current folder
for path in os.listdir():
    if not os.path.isfile(path) or not path.endswith(".pdf"):
        continue

    # Iterate over extracted page elements from a given file
    for page in pdfminer.high_level.extract_pages(path):
        if not isinstance(page, typing.Iterable):
            continue

        # Sort page elements by inverse vertical, then horizontal position
        items = sorted(page, key=lambda it: (-it.bbox[1], it.bbox[0]))

        # Drop elements until the first horizontal line
        items = itertools.dropwhile(lambda it: not isinstance(it, pdfminer.layout.LTLine), items)

        while True:

            # Take all elements until the next horizontal line
            row = itertools.takewhile(lambda it: not isinstance(it, pdfminer.layout.LTFigure), items)

            # Take only elements with text
            row = filter(lambda it: isinstance(it, pdfminer.layout.LTTextBox), row)

            # Sort again by horizontal position only stripping leading and trailing new lines
            row = [it.get_text().strip() for it in sorted(row, key=lambda it: it.bbox[0])]

            # No more elements
            if len(row) == 0:
                break

            # Split dates by space if they are in the same text box
            row = row[0].split(" ") + row[1:] if " " in row[0] else row

            # Split non-alpha (description) lines in each text box
            row = [it.splitlines() if not it[0].isalpha() else [it] for it in row]

            # Chain split lines into a single row again
            row = list(itertools.chain(*row))

            # Check first two elements contain a date (booking/transaction dates)
            if len([it for it in row if is_date(it)]) < 2:
                summary = ' '.join(row).replace('\n', '')
                print(f"Skipping row '{summary}'")
                continue

            # DKB statements lead with the balance from the previous page
            if row[2].startswith("Übertrag von Seite"):

                # Foreign currency conversion
                if len(row) == 13:
                    row = row[:2] + row[3:7] + row[8:10] + row[11:]

                # Domestic currency
                elif len(row) == 8:
                    row = row[:2] + row[3:4] + row[5:6] + row[7:]

            # Simple transaction with domestic currency
            if len(row) == 5 and has_amounts(row, 1):
                item = pd.DataFrame({args.transaction_date: row[0], args.booking_date: row[1],
                                     args.description: row[2], args.amount: f"{row[4]}{row[3]}"}, index=[0])

                df = pd.concat([df, item], axis=0, ignore_index=True)
                continue

            # Transaction with accompanied conversion transaction for foreign currency
            if len(row) == 10 and len(row[-2]) == 1 and len(row[-1]) == 1:
                amounts = (locale.atof(f"{row[8]}{row[6]}"), locale.atof(f"{row[9]}{row[7]}"))
                item_description, fee_description = row[2][:row[2].rfind('\n')], row[2]
                item_amount, fee_amount = min(amounts), max(amounts)

                item = pd.DataFrame({args.transaction_date: row[0], args.booking_date: row[1],
                                     args.description: item_description, args.currency: row[3],
                                     args.original_amount: row[4], args.exchange_rate: row[5],
                                     args.amount: item_amount}, index=[0])

                fee = pd.DataFrame({args.transaction_date: row[0], args.booking_date: row[1],
                                    args.description: fee_description, args.amount: fee_amount}, index=[0])

                df = pd.concat([df, item, fee], axis=0, ignore_index=True)
                continue

df[args.currency] = df[args.currency].fillna("EUR")
# output = path.replace("pdf", "csv")
# print(f"Writing output to file {output}")
# df.to_csv(output, index=False)
print(df)
