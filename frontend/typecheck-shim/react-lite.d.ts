// OFFLINE TYPECHECK SHIM — used only by tsconfig.shim.json when @types/react cannot be installed.
// With network access, `npm install` provides the real @types/react and `npm run typecheck` ignores this folder.
type AnyFn = (e: any) => any;
type Handlers = {
  onClick?: AnyFn; onChange?: AnyFn; onSubmit?: AnyFn; onKeyDown?: AnyFn; onDragOver?: AnyFn; onDragLeave?: AnyFn; onDrop?: AnyFn;
  onMouseDown?: AnyFn; onFocus?: AnyFn; onBlur?: AnyFn; onInput?: AnyFn; [prop: string]: any;
};
declare namespace JSX {
  interface Element { }
  interface IntrinsicElements { [tag: string]: Handlers }
  interface ElementChildrenAttribute { children: {} }
  interface IntrinsicAttributes { key?: string | number }
}
declare namespace React {
  type ReactNode = any; type FormEvent = any; type ChangeEvent<T = any> = any; type MouseEvent<T = any> = any;
}
declare module "react/jsx-runtime" {
  export namespace JSX { interface Element { } interface IntrinsicElements { [tag: string]: Handlers } interface ElementChildrenAttribute { children: {} } interface IntrinsicAttributes { key?: string | number } }
  export function jsx(type: any, props: any, key?: any): any;
  export function jsxs(type: any, props: any, key?: any): any;
  export const Fragment: any;
}
declare module "react" {
  export type ReactNode = any;
  export type Dispatch<A> = (a: A) => void;
  export type SetStateAction<S> = S | ((prev: S) => S);
  export type AnchorHTMLAttributes<T> = Handlers & { href?: string; target?: string; className?: string; style?: any; children?: any; [k: string]: any };
  export type FC<P = {}> = (props: P) => any;
  export interface Context<T> { Provider: (props: { value: T; children?: any }) => any; __t?: T }
  export function createContext<T>(def: T): Context<T>;
  export function useContext<T>(c: Context<T>): T;
  export function useState<S>(init: S | (() => S)): [S, Dispatch<SetStateAction<S>>];
  export function useEffect(f: () => void | (() => void), deps?: readonly unknown[]): void;
  export function useMemo<T>(f: () => T, deps: readonly unknown[]): T;
  export function useCallback<T extends (...a: any[]) => any>(f: T, deps: readonly unknown[]): T;
  export function useRef<T>(init: T): { current: T };
  export function useRef<T>(init: T | null): { current: T | null };
  export function useId(): string;
}
declare module "react-dom/client" {
  export function createRoot(el: Element | DocumentFragment): { render(node: any): void; unmount(): void };
}
