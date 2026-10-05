import { ChevronDownIcon } from "./icons";
import { Menu } from "./Menu";

export interface SelectOption<T extends string | number> {
  value: T;
  label: string;
}

/** App-styled dropdown (a native <select> list is unstylable). `variant="text"` is the borderless form. */
export function Select<T extends string | number>({
  label,
  value,
  options,
  onChange,
  disabled = false,
  variant = "field",
  className = "",
}: {
  label: string;
  value: T;
  options: SelectOption<T>[];
  onChange: (value: T) => void;
  disabled?: boolean;
  variant?: "field" | "text";
  className?: string;
}) {
  const current = options.find((o) => o.value === value);
  return (
    <Menu
      label={label}
      anchored
      disabled={disabled}
      triggerClassName={`select-btn select-${variant} ${className}`}
      trigger={
        <>
          <span className="select-btn-label">{current?.label ?? ""}</span>
          <ChevronDownIcon size={13} />
        </>
      }
      items={options.map((o) => ({
        label: o.label,
        checked: o.value === value,
        onClick: () => o.value !== value && onChange(o.value),
      }))}
    />
  );
}
