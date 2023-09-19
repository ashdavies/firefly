import argparse
import errno
import os
import typing

import pandas as pd
import pdfminer.high_level
import pdfminer.layout
import pdfminer.utils


LTComponent = typing.TypeVar("LTComponent", bound=pdfminer.layout.LTComponent)
T = typing.TypeVar("T")


def contains_exactly(container: pdfminer.layout.LTTextBox, value: str) -> bool:
    return get_first_line(container) == value


def dump(component: LTComponent):
    print(f"{component.bbox}: {', '.join(component.get_text().splitlines())}")


def get_first_line(container: pdfminer.layout.LTTextBox):
    return next(iter(container.get_text().splitlines()))


def get_bottom(component: pdfminer.layout.LTComponent):
    return component.bbox[1]


def get_left(component: pdfminer.layout.LTComponent):
    return component.bbox[0]


def get_text(component: pdfminer.layout.LTTextBox):
    return component.get_text().strip()


def get_top(component: pdfminer.layout.LTComponent):
    return component.bbox[3]


def group_by(iterable: typing.Iterator[T], key_func=lambda it: it, limit=None):
    identity_key = last_key = object()
    buffer = []
    size = 0

    for item in iterable:
        if limit is None or size < limit - 1:
            current_key = key_func(item)

            if last_key == identity_key:
                last_key = current_key

            if current_key != last_key:
                size = size + 1
                yield buffer
                buffer = []

            last_key = current_key
        buffer.append(item)

    if len(buffer) > 0:
        yield buffer


pdfminer.layout.LTComponent.bottom = property(get_bottom)
pdfminer.layout.LTComponent.left = property(get_left)
pdfminer.layout.LTComponent.top = property(get_top)
pdfminer.layout.LTTextBox.text = property(get_text)


def snap(component: LTComponent, grid_size: int) -> LTComponent:
    def _round_to(value: float, size: int = grid_size):
        return round(value / size) * size

    left = _round_to(component.left)
    bottom = _round_to(component.bottom)
    end = round(component.bbox[2] / grid_size) * grid_size
    top = _round_to(component.top)

    component.bbox = (left, bottom, end, top)
    return component


parser = argparse.ArgumentParser()
parser.add_argument("--input-file")
parser.add_argument("--amount-heading", default="Betrag (EUR)")
parser.add_argument("--grid-size", default=1)
parser.add_argument("--max-width", default=65)
args = parser.parse_args()

if not os.path.exists(args.input_file):
    raise FileNotFoundError(errno.ENOENT, os.strerror(errno.ENOENT), args.input_file)

if ".pdf" not in args.input_file:
    raise Exception(errno.EINVAL, os.strerror(errno.EINVAL), args.input_file)

doc_df = pd.DataFrame()

for page in pdfminer.high_level.extract_pages(args.input_file):
    if not isinstance(page, typing.Iterable):
        continue

    # Get all layout elements from PDF that contains text, snap to specified grid size
    containers = [snap(it, int(args.grid_size)) for it in page if isinstance(it, pdfminer.layout.LTTextBox)]

    # Detect one of the headers matching the specified text
    try:
        amount_heading = next(it for it in containers if contains_exactly(it, args.amount_heading))
    except StopIteration:
        print(f"Amount heading '{args.amount_heading}' not found in page")
        continue

    # Get all items with the same horizontal position as the detected header
    headers = sorted([it for it in containers if it.bbox[3] == amount_heading.bbox[3]], key=lambda it: it.bbox[0])

    # Drop items above recognised amount heading
    containers = [it for it in containers if it.bbox[2] >= headers[0].bbox[0] and it.bbox[3] <= headers[0].bbox[1]]

    # Drop items bigger than maximum threshold of page size
    containers = [it for it in containers if ((it.bbox[2] - it.bbox[0]) / page.width) * 100 <= int(args.max_width)]

    # Sort items by horizontal and vertical position
    containers = sorted(containers, key=lambda it: (it.bbox[0], -it.bbox[1]))

    # Group elements by x position with a maximum size of the amount of headers
    containers = group_by(containers, lambda it: it.bbox[0], len(headers))

    # Store the positions of the first column to handle multi-line descriptions
    positions = None

    # Create data frame with grouped data and headers
    page_df = pd.DataFrame(columns=[it.text for it in headers])

    # Populate the data frame by header
    for header in headers:
        column = sorted(next(containers), key=lambda it: -it.bbox[1])
        key = header.text

        if positions is None:
            positions = [row.top for row in column]
            page_df[key] = [it.text for it in column]
            continue

        output = []
        cursor = 0

        for row in column:
            if cursor >= len(positions):
                print(f"Ignoring row with text '{row.text}'")
                continue

            if cursor > 0 and row.top > positions[cursor]:
                output[cursor - 1] = f"{output[cursor - 1]}\n{row.text}"
                continue

            output.append(row.text)
            cursor = cursor + 1

        page_df[key] = output

    doc_df = pd.concat([doc_df, page_df])

for column in doc_df.columns:
    columns = column.split("\n")
    if len(columns) > 1:
        doc_df[columns] = doc_df[column].str.split("\n", expand=True)
        doc_df = doc_df[columns + [it for it in doc_df.columns if it not in columns]]
        doc_df = doc_df.drop(column, axis=1)

output_file = args.input_file.replace("pdf", "csv")
print(f"Writing output to file {output_file}")
doc_df.to_csv(output_file, index=False)
