import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { useAuthStore } from "./store/auth";
import Layout, { NAV, puedeVer } from "./components/Layout";
import { Loading } from "./components/ui";
import Login from "./pages/Login";
import Usuarios from "./pages/Usuarios";
import Configuracion from "./pages/Configuracion";
import Panel from "./Panel.jsx";
import Formulario from "./Formulario.jsx";
import Planeacion from "./Planeacion.jsx";

/** Exige sesion y, si se indica, un permiso (como ProtectedRoute en produccionweb). */
function Protegida({ modulo, accion = "ver", children }) {
  const { user, cargando } = useAuthStore();
  if (cargando) return <div className="p-10"><Loading label="Verificando sesión..." /></div>;
  if (!user) return <Navigate to="/login" replace />;
  if (modulo && !user.permisos?.[modulo]?.[accion]) return <Navigate to="/" replace />;
  return <Layout>{children}</Layout>;
}

/** "/" lleva a la primera pantalla que el rol puede ver. */
function Inicio() {
  const { user, cargando } = useAuthStore();
  if (cargando) return <div className="p-10"><Loading label="Verificando sesión..." /></div>;
  if (!user) return <Navigate to="/login" replace />;
  const primera = NAV.find((n) => puedeVer(user, n));
  if (primera) return <Navigate to={primera.to} replace />;
  return (
    <Layout>
      <div className="p-10 text-center text-slate-500">
        Tu rol no tiene acceso a ninguna pantalla todavía. Pide a un administrador que te asigne permisos.
      </div>
    </Layout>
  );
}

function NuevaSolicitud() {
  const navigate = useNavigate();
  return <Formulario alCrear={(irAlPanel) => irAlPanel && navigate("/seguimiento")} />;
}

function LoginRuta() {
  const { user, cargando } = useAuthStore();
  if (!cargando && user) return <Navigate to="/" replace />;
  return <Login />;
}

export default function App() {
  const cargar = useAuthStore((s) => s.cargar);
  useEffect(() => { cargar(); }, [cargar]);

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginRuta />} />
        <Route path="/" element={<Inicio />} />
        <Route path="/seguimiento" element={<Protegida modulo="seguimiento"><Panel /></Protegida>} />
        <Route path="/nueva" element={<Protegida modulo="solicitudes" accion="crear"><NuevaSolicitud /></Protegida>} />
        <Route path="/planeacion" element={<Protegida modulo="planeacion"><Planeacion /></Protegida>} />
        <Route path="/usuarios" element={<Protegida modulo="usuarios"><Usuarios /></Protegida>} />
        <Route path="/configuracion" element={<Protegida modulo="configuracion"><Configuracion /></Protegida>} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
