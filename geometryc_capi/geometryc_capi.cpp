/*
 * Implementation of C API for bgfx geometry compiler (geometryc).
 * Wraps geometryc.cpp core logic, replacing file I/O with memory I/O.
 */

#include "geometryc_capi.h"

// Prevent main() from being compiled into this translation unit.
#define GEOMETRYC_CAPI 1

// Include the full geometryc source to access all internal types and functions.
// CGLTF_IMPLEMENTATION is already defined inside geometryc.cpp.
#include "../geometryc/geometryc.cpp"

// =============================================================================
// Helper: bx::MemoryWriter with externally-owned buffer
// =============================================================================

struct MemoryWriter : public bx::WriterI
{
	MemoryWriter()
		: m_data(NULL)
		, m_size(0)
		, m_capacity(0)
	{
	}

	~MemoryWriter()
	{
	}

	int32_t write(const void* _data, int32_t _size, bx::Error* _err) override
	{
		BX_UNUSED(_err);

		if (m_size + _size > m_capacity)
		{
			// Grow by 2x or to fit, whichever is larger.
			uint32_t newCapacity = bx::max(m_capacity * 2, m_capacity + _size + 65536);
			uint8_t* newData = new uint8_t[newCapacity];
			if (m_data != NULL)
			{
				bx::memCopy(newData, m_data, m_size);
				delete [] m_data;
			}
			m_data = newData;
			m_capacity = newCapacity;
		}

		bx::memCopy(m_data + m_size, _data, _size);
		m_size += _size;
		return _size;
	}

	uint8_t*  m_data;
	uint32_t  m_size;
	uint32_t  m_capacity;
};

// =============================================================================
// gc_convert
// =============================================================================

int32_t gc_convert(
	  const void* _input_data
	, uint32_t    _input_size
	, const char* _input_ext
	, const char* _base_path
	, const gc_config_t* _config
	, gc_result_t* _out_result
)
{
	// ----- Default config -----
	float scale = 1.0f;
	bool compress = false;
	uint32_t packNormal = 0;
	uint32_t packUv = 0;
	bool ccw = false;
	bool flipV = false;
	bool hasTangent = false;
	bool hasBc = false;
	CoordinateSystem outputCoordinateSystem;
	outputCoordinateSystem.m_handedness = bx::Handedness::Left;
	outputCoordinateSystem.m_forward = Axis::PositiveZ;
	outputCoordinateSystem.m_up = Axis::PositiveY;

	if (_config != NULL)
	{
		scale = _config->scale;
		compress = _config->compress;
		packNormal = _config->pack_normal;
		packUv = _config->pack_uv;
		ccw = _config->ccw;
		flipV = _config->flip_v;
		hasTangent = _config->has_tangent;
		hasBc = _config->has_barycentric;

		switch (_config->coord_system)
		{
		case GC_COORD_LH_UP_Y:
			outputCoordinateSystem.m_handedness = bx::Handedness::Left;
			outputCoordinateSystem.m_forward = Axis::PositiveZ;
			outputCoordinateSystem.m_up = Axis::PositiveY;
			break;
		case GC_COORD_LH_UP_Z:
			outputCoordinateSystem.m_handedness = bx::Handedness::Left;
			outputCoordinateSystem.m_forward = Axis::PositiveY;
			outputCoordinateSystem.m_up = Axis::PositiveZ;
			break;
		case GC_COORD_RH_UP_Y:
			outputCoordinateSystem.m_handedness = bx::Handedness::Right;
			outputCoordinateSystem.m_forward = Axis::PositiveZ;
			outputCoordinateSystem.m_up = Axis::PositiveY;
			break;
		case GC_COORD_RH_UP_Z:
			outputCoordinateSystem.m_handedness = bx::Handedness::Right;
			outputCoordinateSystem.m_forward = Axis::PositiveY;
			outputCoordinateSystem.m_up = Axis::PositiveZ;
			break;
		}
	}

	// ----- Parse -----
	bx::StringView ext(_input_ext);
	char* data = new char[_input_size + 1];
	bx::memCopy(data, _input_data, _input_size);
	data[_input_size] = '\0';

	Mesh mesh;
	if (0 == bx::strCmpI(ext, ".obj")
	||  0 == bx::strCmpI(ext, "obj") )
	{
		parseObj(data, _input_size, &mesh, hasBc);
	}
	else if (0 == bx::strCmpI(ext, ".gltf")
		  || 0 == bx::strCmpI(ext, "gltf")
		  || 0 == bx::strCmpI(ext, ".glb")
		  || 0 == bx::strCmpI(ext, "glb") )
	{
		bx::StringView basePath(_base_path != NULL ? _base_path : "");
		parseGltf(data, _input_size, &mesh, hasBc, basePath);
	}
	else
	{
		delete [] data;
		return -1; // Unsupported format
	}

	delete [] data;

	// ----- Process mesh (replicates the core of main() ) -----
	std::sort(mesh.m_groups.begin(), mesh.m_groups.end(), GroupSortByMaterial() );

	bool changeWinding = ccw;

	if (scale != 1.0f)
	{
		for (Vec3Array::iterator it = mesh.m_positions.begin(), itEnd = mesh.m_positions.end(); it != itEnd; ++it)
		{
			it->x *= scale;
			it->y *= scale;
			it->z *= scale;
		}
	}

	{
		float meshTransform[16];
		mtxCoordinateTransform(meshTransform, mesh.m_coordinateSystem);

		float meshInvTransform[16];
		bx::mtxTranspose(meshInvTransform, meshTransform);

		float outTransform[16];
		mtxCoordinateTransform(outTransform, outputCoordinateSystem);

		float transform[16];
		bx::mtxMul(transform, meshInvTransform, outTransform);

		if (mtxDeterminant(transform) < 0.0f)
		{
			changeWinding = !changeWinding;
		}

		float identity[16];
		bx::mtxIdentity(identity);

		if (0 != bx::memCmp(identity, transform, sizeof(transform)))
		{
			for (Vec3Array::iterator it = mesh.m_positions.begin(), itEnd = mesh.m_positions.end(); it != itEnd; ++it)
			{
				*it = bx::mul(*it, transform);
			}

			for (Vec3Array::iterator it = mesh.m_normals.begin(), itEnd = mesh.m_normals.end(); it != itEnd; ++it)
			{
				*it = bx::mul(*it, transform);
			}
		}
	}

	bool hasColor = false;
	bool hasNormal = false;
	bool hasTexcoord = false;

	{
		for (TriangleArray::iterator it = mesh.m_triangles.begin(), itEnd = mesh.m_triangles.end(); it != itEnd && !hasTexcoord; ++it)
		{
			for (uint32_t i = 0; i < 3; ++i)
			{
				hasTexcoord |= -1 != it->m_index[i].m_texcoord;
			}
		}

		for (TriangleArray::iterator it = mesh.m_triangles.begin(), itEnd = mesh.m_triangles.end(); it != itEnd && !hasNormal; ++it)
		{
			for (uint32_t i = 0; i < 3; ++i)
			{
				hasNormal |= -1 != it->m_index[i].m_normal;
			}
		}
	}

	if (changeWinding)
	{
		for (TriangleArray::iterator it = mesh.m_triangles.begin(), itEnd = mesh.m_triangles.end(); it != itEnd; ++it)
		{
			bx::swap(it->m_index[1], it->m_index[2]);
		}
	}

	// ----- Build vertex layout -----
	bgfx::VertexLayout layout;
	layout.begin();
	layout.add(bgfx::Attrib::Position, 3, bgfx::AttribType::Float);

	if (hasColor)
	{
		layout.add(bgfx::Attrib::Color0, 4, bgfx::AttribType::Uint8, true);
	}

	if (hasBc)
	{
		layout.add(bgfx::Attrib::Color1, 4, bgfx::AttribType::Uint8, true);
	}

	if (hasTexcoord)
	{
		switch (packUv)
		{
		default:
		case 0:
			layout.add(bgfx::Attrib::TexCoord0, 2, bgfx::AttribType::Float);
			break;

		case 1:
			layout.add(bgfx::Attrib::TexCoord0, 2, bgfx::AttribType::Half);
			break;
		}
	}

	if (hasNormal)
	{
		hasTangent &= hasTexcoord;

		switch (packNormal)
		{
		default:
		case 0:
			layout.add(bgfx::Attrib::Normal, 3, bgfx::AttribType::Float);
			if (hasTangent)
			{
				layout.add(bgfx::Attrib::Tangent, 4, bgfx::AttribType::Float);
			}
			break;

		case 1:
			layout.add(bgfx::Attrib::Normal, 4, bgfx::AttribType::Uint8, true, true);
			if (hasTangent)
			{
				layout.add(bgfx::Attrib::Tangent, 4, bgfx::AttribType::Uint8, true, true);
			}
			break;
		}
	}

	layout.end();

	// ----- Allocate working buffers -----
	uint32_t stride = layout.getStride();
	uint8_t* vertexData = new uint8_t[mesh.m_triangles.size() * 3 * stride];
	uint16_t* indexData = new uint16_t[mesh.m_triangles.size() * 3];
	int32_t numVertices = 0;
	int32_t numIndices = 0;

	uint8_t* vertices = vertexData;
	uint16_t* indices = indexData;

	const uint32_t tableSize = 65536 * 2;
	const uint32_t hashmod = tableSize - 1;
	uint32_t* table = new uint32_t[tableSize];
	bx::memSet(table, 0xff, tableSize * sizeof(uint32_t));

	stl::string material = mesh.m_groups.empty() ? "" : mesh.m_groups.begin()->m_material;

	PrimitiveArray primitives;

	Primitive prim;
	prim.m_startVertex = 0;
	prim.m_startIndex = 0;

	uint32_t positionOffset = layout.getOffset(bgfx::Attrib::Position);
	uint32_t color0Offset   = layout.getOffset(bgfx::Attrib::Color0);

	Group sentinelGroup;
	sentinelGroup.m_startTriangle = 0;
	sentinelGroup.m_numTriangles = UINT32_MAX;
	mesh.m_groups.push_back(sentinelGroup);

	// ----- Write using MemoryWriter instead of FileWriter -----
	MemoryWriter memWriter;
	bx::Error err;

	int32_t writtenPrimitives = 0;
	int32_t writtenVertices = 0;
	int32_t writtenIndices = 0;

	uint32_t ii = 0;
	for (GroupArray::const_iterator groupIt = mesh.m_groups.begin(); groupIt != mesh.m_groups.end(); ++groupIt, ++ii)
	{
		const bool sentinel = groupIt->m_startTriangle == 0 && groupIt->m_numTriangles == UINT32_MAX;

		for (uint32_t tri = groupIt->m_startTriangle, end = tri + groupIt->m_numTriangles; tri < end; ++tri)
		{
			if (0 != bx::strCmp(material.c_str(), groupIt->m_material.c_str() )
			||  sentinel
			||  65533 <= numVertices)
			{
				prim.m_numVertices = numVertices - prim.m_startVertex;
				prim.m_numIndices  = numIndices  - prim.m_startIndex;

				if (0 < prim.m_numVertices)
				{
					primitives.push_back(prim);
				}

				if (hasTangent)
				{
					calcTangents(vertexData, uint16_t(numVertices), layout, indexData, numIndices);
				}

				for (PrimitiveArray::const_iterator primIt = primitives.begin(); primIt != primitives.end(); ++primIt)
				{
					const Primitive& prim1 = *primIt;
					optimizeVertexCache(indexData + prim1.m_startIndex, prim1.m_numIndices, numVertices);
				}

				numVertices = optimizeVertexFetch(indexData, numIndices, vertexData, numVertices, uint16_t(stride));

				if (0 < numVertices
				&&  0 < numIndices)
				{
					write(&memWriter, vertexData, numVertices, layout, indexData, numIndices, compress, material, primitives, &err);
				}
				primitives.clear();

				bx::memSet(table, 0xff, tableSize * sizeof(uint32_t));

				++writtenPrimitives;
				writtenVertices += numVertices;
				writtenIndices += numIndices;

				vertices = vertexData;
				indices  = indexData;
				numVertices = 0;
				numIndices  = 0;
				prim.m_startVertex = 0;
				prim.m_startIndex  = 0;

				material = groupIt->m_material;

				if (sentinel)
				{
					break;
				}
			}

			TriIndices& triangle = mesh.m_triangles[tri];
			for (uint32_t edge = 0; edge < 3; ++edge)
			{
				Index3& index = triangle.m_index[edge];

				float* position = (float*)(vertices + positionOffset);
				bx::memCopy(position, &mesh.m_positions[index.m_position], 3*sizeof(float));

				if (hasColor)
				{
					uint32_t* color0 = (uint32_t*)(vertices + color0Offset);
					*color0 = rgbaToAbgr(numVertices%255, numIndices%255, 0, 0xff);
				}

				if (hasBc)
				{
					const float bc[4] =
					{
						(index.m_vbc == 0) ? 1.0f : 0.0f,
						(index.m_vbc == 1) ? 1.0f : 0.0f,
						(index.m_vbc == 2) ? 1.0f : 0.0f,
						0.0f
					};
					bgfx::vertexPack(bc, true, bgfx::Attrib::Color1, layout, vertices);
				}

				if (hasTexcoord)
				{
					float uv[2];
					bx::memCopy(uv, &mesh.m_texcoords[index.m_texcoord == -1 ? 0 : index.m_texcoord], 2*sizeof(float));

					if (flipV)
					{
						uv[1] = -uv[1];
					}

					bgfx::vertexPack(uv, true, bgfx::Attrib::TexCoord0, layout, vertices);
				}

				if (hasNormal)
				{
					float normal[4];
					bx::store(normal, bx::normalize(bx::load<bx::Vec3>(&mesh.m_normals[index.m_normal == -1 ? 0 : index.m_normal])));
					normal[3] = 0.0f;
					bgfx::vertexPack(normal, true, bgfx::Attrib::Normal, layout, vertices);
				}

				uint32_t hash = bx::hash<bx::HashMurmur2A>(vertices, stride);
				size_t bucket = hash & hashmod;
				uint32_t vertexIndex = UINT32_MAX;

				for (size_t probe = 0; probe <= hashmod; ++probe)
				{
					uint32_t& item = table[bucket];

					if (item == ~0u)
					{
						vertices += stride;
						item = numVertices++;
						vertexIndex = item;
						break;
					}

					if (0 == bx::memCmp(vertexData + item * stride, vertices, stride))
					{
						vertexIndex = item;
						break;
					}

					bucket = (bucket + probe + 1) & hashmod;
				}

				if (vertexIndex == UINT32_MAX)
				{
					delete [] table;
					delete [] indexData;
					delete [] vertexData;
					return -2; // Hash table insert failed
				}

				*indices++ = (uint16_t)vertexIndex;
				++numIndices;
			}
		}

		prim.m_numVertices = numVertices - prim.m_startVertex;
		if (0 < prim.m_numVertices)
		{
			prim.m_numIndices = numIndices - prim.m_startIndex;
			prim.m_name = groupIt->m_name;
			primitives.push_back(prim);
			prim.m_startVertex = numVertices;
			prim.m_startIndex  = numIndices;
		}
	}

	// ----- Fill output result -----
	_out_result->data = memWriter.m_data;
	_out_result->size = memWriter.m_size;
	_out_result->num_vertices = writtenVertices;
	_out_result->num_indices = writtenIndices;
	_out_result->num_primitives = primitives.size();

	_out_result->primitives = new gc_primitive_t[primitives.size()];
	for (uint32_t pi = 0; pi < primitives.size(); ++pi)
	{
		_out_result->primitives[pi].start_vertex = primitives[pi].m_startVertex;
		_out_result->primitives[pi].start_index  = primitives[pi].m_startIndex;
		_out_result->primitives[pi].num_vertices = primitives[pi].m_numVertices;
		_out_result->primitives[pi].num_indices  = primitives[pi].m_numIndices;
		_out_result->primitives[pi].name = NULL;
	}

	// ----- Cleanup -----
	delete [] table;
	delete [] indexData;
	delete [] vertexData;

	// Note: memWriter.m_data is now owned by _out_result.

	return 0;
}

// =============================================================================
// gc_result_free
// =============================================================================

void gc_result_free(gc_result_t* _result)
{
	if (_result == NULL)
	{
		return;
	}

	delete [] (uint8_t*)_result->data;
	_result->data = NULL;
	_result->size = 0;

	delete [] _result->primitives;
	_result->primitives = NULL;
	_result->num_primitives = 0;
}

// =============================================================================
// gc_version
// =============================================================================

void gc_version(int32_t* _major, int32_t* _minor)
{
	if (_major != NULL) *_major = BGFX_GEOMETRYC_VERSION_MAJOR;
	if (_minor != NULL) *_minor = BGFX_GEOMETRYC_VERSION_MINOR;
}