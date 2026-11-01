import { create } from "zustand";
import { enExpiracion, pedir } from "../api";

// Mismo contrato que produccionweb/store/auth.ts (user.nombre, rol, permisos
// {[modulo]: {ver, crear, editar, eliminar}}), pero sin token en localStorage:
// la sesion es una cookie HttpOnly y el usuario se pide a /auth/yo al cargar.
export const useAuthStore = create((set) => ({
  user: null,
  cargando: true,

  cargar: async () => {
    try {
      set({ user: await pedir("/api/auth/yo"), cargando: false });
    } catch {
      set({ user: null, cargando: false });
    }
  },

  login: async (username, password) => {
    const user = await pedir("/api/auth/login", { method: "POST", json: { username, password } });
    set({ user });
  },

  logout: async () => {
    try { await pedir("/api/auth/logout", { method: "POST" }); } catch { /* ya no habia sesion */ }
    set({ user: null });
  },
}));

enExpiracion(() => useAuthStore.setState({ user: null }));

const SIN_PERMISO = { ver: false, crear: false, editar: false, eliminar: false };

export const usePermiso = (modulo) => {
  const permisos = useAuthStore((s) => s.user?.permisos ?? {});
  return permisos[modulo] ?? SIN_PERMISO;
};
