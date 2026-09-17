export PATH="/d/Venv/C_Cpp/llvm-mingw/bin:$PATH"
cd "/d/workspace/Projects/three.cj/httpclient4cj/cxx/openssl" || exit 1
echo "=== Configuring OpenSSL === "
perl ./Configure mingw64 no-weak-ssl-ciphers no-comp no-dso no-engine no-tests no-ssl3 --debug no-shared no-module no-apps no-tests 2>&1
echo "CONFIGURE_EXIT:$?"
echo "=== Building OpenSSL === "
make -j12 2>&1
echo "MAKE_EXIT:$?"
