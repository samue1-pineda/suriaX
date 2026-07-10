import ctypes

class MemoryAllocator:
    def __init__(self,size:int):
        self.memory=bytearray(size)
        self.allocated_blocks={}

    def malloc(self,size:int):
        for i in range(len(self.memory)-size+1):
            if all(b==0 for b in self.memory[i:i+size]):
                self.memory[i:i+size]=bytearray([1]*size)
                memory_block=(ctypes.c_char*size).from_buffer(self.memory,i)
                self.allocated_blocks[id(memory_block)]=(i,size)
                return memory_block
        raise MemoryError('out of memory')
    
    def free(self,memory_block):
        block_id=id(memory_block)
        if block_id not in self.allocated_blocks:
            raise ValueError("bloque de memoria no valida")
        start_index,size=self.allocated_blocks.pop(block_id)
        self.memory[start_index:start_index+size]=bytearray([0]*size)

class Ptr:
    def __init__(self,size:int):
        self.allocator=MemoryAllocator
        self.block=self.allocator.malloc(size)
        self._is_valid=True

    def move(self):
        if not self._is_valid:
            raise RuntimeError("intento de mover recurso que ya tiene dueño")
        new_owner=Ptr.__new__(Ptr)
        new_owner.allocator=self.allocator
        new_owner.block=self.block
        new_owner._is_valid=True

        self._is_valid=False
        self.block=None

        return new_owner
    def read(self):
        if not self._is_valid:
            raise RuntimeError("intento de mover un ptr invalido")
        return self.block
    
    
    def __del__(self):
        if self._is_valid and self.block is not None:
            self.allocator.free(self.block)

class uniquePtr(Ptr):
    pass

class shrdPtr(Ptr):
    pass




def _assign_memory(size_t):
    alloc=MemoryAllocator(1024)
    try:
        m_alloc=alloc.malloc(size_t)
        m_alloc[0]=b'x'
        alloc.free(m_alloc)
        return f"mem used:{m_alloc}"
    except MemoryError as e:
        return str(e)


# NOTA: este modulo es un PROTOTIPO experimental del modelo de memoria y todavia
# no lo usa el pipeline. La clase 'Ptr' aun tiene bugs conocidos (p. ej. usa la
# CLASE MemoryAllocator en vez de una instancia). El demo se ejecuta solo como
# script, nunca al importar (antes 'print(...)' corria en import y ensuciaba
# cualquier proceso que importara este archivo).
if __name__ == "__main__":
    print(_assign_memory(256))