ROW_CHARACTERS = 20 # 20 chars per row
ROW_COUNT = 4 # 4 rows

def add_line(lines, lyric, start, end, add_dash=False):
    line = lyric[start:end].strip()

    if add_dash:
        line += "-"

    lines.append(line)

def remove_parentheses(text):
    parenthesis_depth = 0
    no_parentheses_text = ""

    for character in text:
        if character == "(":
            parenthesis_depth += 1

        elif character == ")" and parenthesis_depth > 0:
            parenthesis_depth -= 1

        elif parenthesis_depth == 0:
            no_parentheses_text += character

    # If any opening parentheses were never closed
    if parenthesis_depth > 0:
        return text

    no_parentheses_text = " ".join(no_parentheses_text.split())

    return no_parentheses_text

def format_text_to_bounds(raw_text):
    """
    Main interface for external scripts.
    Applies different strategies until the text fits the display bounds.
    """

    # First try the original text with normal word splitting
    lines = fit_to_layout(raw_text)

    # Return if successful
    if lines is not None:
        return lines

    # Handle the overflow
    # Try no parentheses
    no_parentheses_text = remove_parentheses(raw_text)
    lines = fit_to_layout(no_parentheses_text)

    # Return if successful
    if lines is not None:
            return lines

    # Return midword splits + parentheses attempt regardless of its success.
    lines =  fit_to_layout(no_parentheses_text, allow_midword_splits=True, 
                            allow_row_overflow=True)

    return lines[:ROW_COUNT]


def fit_to_layout(text, allow_midword_splits=False, allow_row_overflow=False):
    """
    Splits text up into lines according to the character grid dimensions.
    Returns lines as a list.
    Returns None if text doesnt fit.
    """

    current_word_start = 0
    line_start = 0
    current_row_number = 1

    lines = []

    for index, character in enumerate(text):
        # When we get to a space, the next index is the start of a word
        if character == " " or character == "-":
            current_word_start = index + 1

        # Once we get to a letter longer than the row, and we're not on the final line
        if index - line_start >= ROW_CHARACTERS:
            # If there's need for more than ROW_COUNT rows
            if current_row_number >= ROW_COUNT and not allow_row_overflow:
                return None

            # If words are allowed to be split in the middle
            if allow_midword_splits:
                # Leave final character free for a dash
                split_position = line_start + ROW_CHARACTERS - 1

                # Split it and add a dash
                add_line(lines, text, line_start, split_position, add_dash=True)

                # Next line starts where we stopped splitting
                # (the dash wasn't part of the original text)
                line_start = split_position
                current_word_start = split_position

            # If there has been a word break on this line
            elif current_word_start > line_start:

                # Add everything up to the start of the next word
                add_line(lines, text, line_start, current_word_start)

                # Then set the index of the string where we start the next line
                line_start = current_word_start

            else:  # If the current word is longer than the line

                # Leave final character free for a dash
                split_position = line_start + ROW_CHARACTERS - 1

                # Split it and add a dash
                add_line(lines, text, line_start, split_position, add_dash=True)

                # Next line starts where we stopped splitting
                # (the dash wasn't part of the original text)
                line_start = split_position

            # Track current row
            current_row_number += 1

    # Add whatever is left after the loop
    if line_start < len(text):
        add_line(lines, text, line_start, len(text))

    return lines