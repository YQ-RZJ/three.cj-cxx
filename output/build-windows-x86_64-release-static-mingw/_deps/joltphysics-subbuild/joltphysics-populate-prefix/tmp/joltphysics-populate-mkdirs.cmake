# Distributed under the OSI-approved BSD 3-Clause License.  See accompanying
# file Copyright.txt or https://cmake.org/licensing for details.

cmake_minimum_required(VERSION 3.5)

file(MAKE_DIRECTORY
  "C:/workspace/Web/24w/three.cj/cxx/JoltPhysics"
  "C:/workspace/Web/24w/three.cj/cxx/output/build-windows-x86_64-release-static-mingw/_deps/joltphysics-build"
  "C:/workspace/Web/24w/three.cj/cxx/output/build-windows-x86_64-release-static-mingw/_deps/joltphysics-subbuild/joltphysics-populate-prefix"
  "C:/workspace/Web/24w/three.cj/cxx/output/build-windows-x86_64-release-static-mingw/_deps/joltphysics-subbuild/joltphysics-populate-prefix/tmp"
  "C:/workspace/Web/24w/three.cj/cxx/output/build-windows-x86_64-release-static-mingw/_deps/joltphysics-subbuild/joltphysics-populate-prefix/src/joltphysics-populate-stamp"
  "C:/workspace/Web/24w/three.cj/cxx/output/build-windows-x86_64-release-static-mingw/_deps/joltphysics-subbuild/joltphysics-populate-prefix/src"
  "C:/workspace/Web/24w/three.cj/cxx/output/build-windows-x86_64-release-static-mingw/_deps/joltphysics-subbuild/joltphysics-populate-prefix/src/joltphysics-populate-stamp"
)

set(configSubDirs )
foreach(subDir IN LISTS configSubDirs)
    file(MAKE_DIRECTORY "C:/workspace/Web/24w/three.cj/cxx/output/build-windows-x86_64-release-static-mingw/_deps/joltphysics-subbuild/joltphysics-populate-prefix/src/joltphysics-populate-stamp/${subDir}")
endforeach()
if(cfgdir)
  file(MAKE_DIRECTORY "C:/workspace/Web/24w/three.cj/cxx/output/build-windows-x86_64-release-static-mingw/_deps/joltphysics-subbuild/joltphysics-populate-prefix/src/joltphysics-populate-stamp${cfgdir}") # cfgdir has leading slash
endif()
