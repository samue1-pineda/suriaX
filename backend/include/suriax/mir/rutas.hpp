// 'lib/sistema/rutas' en la VM: las rutas como las calcula 'os.path' de Python.
//
// No son reglas propias: el compilador de Python (la V0) ubica las librerias
// y escribe sus rutas en el .phir con 'os.path', y el compilador escrito en
// suriaX (la V1), que corre en esta VM, tiene que producir EXACTAMENTE las
// mismas cadenas. Por eso cada funcion es el algoritmo de 'ntpath' (Windows)
// o de 'posixpath' (los demas), y en Windows se usan las mismas llamadas al
// sistema que usa Python ('GetFullPathNameW' para 'abspath',
// 'GetCurrentDirectoryW' para 'getcwd'). La prueba diferencial
// (test_vm_diferencial_system) las compara con Python en el mismo sistema.
//
// Las cadenas son UTF-8, como todas las de la VM.
#pragma once

#include <string>

namespace suriax::rutas {

std::string directorio_actual();                         // os.getcwd()
std::string entorno(const std::string& nombre);          // os.environ.get(n, "")
std::string separador();                                 // os.sep
std::string absoluta(const std::string& ruta);           // os.path.abspath
std::string normaliza(const std::string& ruta);          // os.path.normpath
std::string une(const std::string& a, const std::string& b);  // os.path.join
std::string carpeta_de(const std::string& ruta);         // os.path.dirname
std::string nombre_de(const std::string& ruta);          // os.path.basename
bool es_carpeta(const std::string& ruta);                // os.path.isdir
bool es_archivo(const std::string& ruta);                // os.path.isfile

}  // namespace suriax::rutas
