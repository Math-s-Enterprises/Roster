import React, { useEffect, useLayoutEffect, useRef, useState } from "react";

/**
 * The roster-group switcher.
 *
 * A native <select> draws its open list with the operating system: its own
 * font, its own colours, its own row height, none of which follow the theme.
 * This is a button and a listbox instead, so the open list is ours.
 *
 * Replacing a native control means owning what it gave for free, so the
 * keyboard behaviour is implemented rather than assumed: Up and Down move,
 * Home and End jump, Enter or Space picks, Escape closes and puts focus
 * back on the button, and Tab closes without choosing. Clicking outside
 * closes it too. The button is a combobox and the list a listbox, so screen
 * readers announce it as the same kind of control it replaced.
 */
export default function RosterGroupSelect({ value, options, onChange, label = "Current roster group" }) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(() => Math.max(0, options.indexOf(value)));
  const buttonRef = useRef(null);
  const listRef = useRef(null);
  const wrapRef = useRef(null);

  // Opening from the keyboard should land on the current choice, not the top.
  useLayoutEffect(() => {
    if (open) {
      setActive(Math.max(0, options.indexOf(value)));
      listRef.current?.focus();
    }
  }, [open, options, value]);

  useEffect(() => {
    if (!open) return undefined;
    const onPointerDown = (event) => {
      if (!wrapRef.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  const choose = (index) => {
    const next = options[index];
    setOpen(false);
    buttonRef.current?.focus();
    if (next && next !== value) onChange(next);
  };

  const onListKeyDown = (event) => {
    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        setActive((i) => Math.min(options.length - 1, i + 1));
        break;
      case "ArrowUp":
        event.preventDefault();
        setActive((i) => Math.max(0, i - 1));
        break;
      case "Home":
        event.preventDefault();
        setActive(0);
        break;
      case "End":
        event.preventDefault();
        setActive(options.length - 1);
        break;
      case "Enter":
      case " ":
        event.preventDefault();
        choose(active);
        break;
      case "Escape":
        event.preventDefault();
        setOpen(false);
        buttonRef.current?.focus();
        break;
      case "Tab":
        setOpen(false);
        break;
      default:
        break;
    }
  };

  return (
    <span className="nv-ws" ref={wrapRef}>
      <button
        type="button"
        ref={buttonRef}
        data-testid="roster-group-switch"
        className="nv-ws-button"
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls="nv-ws-list"
        aria-label={label}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            setOpen(true);
          }
        }}
      >
        <span className="nv-ws-value">{value}</span>
        <span className="nv-ws-caret" data-open={open} aria-hidden="true" />
      </button>

      {open && (
        <ul
          id="nv-ws-list"
          ref={listRef}
          className="nv-ws-list"
          role="listbox"
          tabIndex={-1}
          aria-label={label}
          aria-activedescendant={`nv-ws-opt-${active}`}
          onKeyDown={onListKeyDown}
        >
          {options.map((name, index) => (
            <li
              key={name}
              id={`nv-ws-opt-${index}`}
              role="option"
              aria-selected={name === value}
              className="nv-ws-option"
              data-active={index === active}
              // Mouse and keyboard highlight the same row, so moving the
              // pointer does not leave two rows looking chosen.
              onMouseEnter={() => setActive(index)}
              onClick={() => choose(index)}
            >
              <span className="nv-ws-tick" data-on={name === value} aria-hidden="true" />
              {name}
            </li>
          ))}
        </ul>
      )}
    </span>
  );
}
