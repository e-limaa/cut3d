import {useEffect,useRef,useState} from 'react';
import {useFrame,useThree,type ThreeEvent} from '@react-three/fiber';
import {Line} from '@react-three/drei';
import * as THREE from 'three';
import type {FreeCut} from './freeCut';
import {getConnectorFrame} from './geometry/connectorFrame';
import {pickConnectorPosition} from './connectorInteraction';

type Mode='position'|'diameter'|'length'|'thickness';
export default function ConnectorGizmo({cut,onCut,onDrag}:{cut:FreeCut;onCut:(cut:FreeCut)=>void;onDrag:(dragging:boolean)=>void}) {
  const {camera,gl,invalidate}=useThree();
  const [drag,setDrag]=useState<{mode:Mode;x:number;y:number;cut:FreeCut;direction:THREE.Vector2}|null>(null);
  const handles=useRef<(THREE.Mesh|null)[]>([]);
  const c=cut.connector!, frame=getConnectorFrame(cut);
  const center=new THREE.Vector3(...frame.center), axis=new THREE.Vector3(...frame.normal).multiplyScalar(c.side), tangent=new THREE.Vector3(...frame.tangent);
  const tip=center.clone().addScaledVector(axis,c.length+cut.kerf/2);
  const rim=center.clone().addScaledVector(tangent,c.diameter/2);
  const lateral=new THREE.Vector3().crossVectors(axis,tangent);
  const edge=center.clone().addScaledVector(lateral,(c.thickness??c.diameter/2)/2);
  useFrame(({size})=>{
    const scale=camera instanceof THREE.OrthographicCamera ? (camera.top-camera.bottom)/(camera.zoom*size.height)*5 : center.distanceTo(camera.position)*.008;
    handles.current.forEach(mesh=>mesh?.scale.setScalar(scale));
  });
  useEffect(()=>()=>onDrag(false),[onDrag]);
  useEffect(()=>{
    if(!drag) return;
    const canvas=gl.domElement;
    const move=(event:PointerEvent)=>{
      const rect=canvas.getBoundingClientRect();
      if(drag.mode==='position') {
        const raycaster=new THREE.Raycaster();
        raycaster.setFromCamera(new THREE.Vector2((event.clientX-rect.left)/rect.width*2-1,1-(event.clientY-rect.top)/rect.height*2),camera);
        const point=pickConnectorPosition(drag.cut,raycaster.ray);
        if(point) onCut({...drag.cut,connector:{...drag.cut.connector!,...point}});
      } else {
        const delta=new THREE.Vector2(event.clientX-drag.x,event.clientY-drag.y);
        const change=delta.dot(drag.direction)/drag.direction.lengthSq();
        const base=drag.cut.connector![drag.mode] ?? drag.cut.connector!.diameter/2;
        onCut({...drag.cut,connector:{...drag.cut.connector!,[drag.mode]:Math.max(.1,base+change*(drag.mode==='length'?1:2))}});
      }
      invalidate();
    };
    const up=()=>{setDrag(null);onDrag(false);canvas.style.cursor='';};
    const key=(event:KeyboardEvent)=>{if(event.key==='Escape'){onCut(drag.cut);up();}};
    window.addEventListener('pointermove',move);window.addEventListener('pointerup',up);window.addEventListener('pointercancel',up);window.addEventListener('keydown',key);
    return()=>{window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',up);window.removeEventListener('pointercancel',up);window.removeEventListener('keydown',key);};
  },[drag,camera,gl,onCut,onDrag,invalidate]);
  const down=(mode:Mode,event:ThreeEvent<PointerEvent>)=>{
    if(event.button !== 0) return;
    event.stopPropagation();
    const rect=gl.domElement.getBoundingClientRect();
    const a=center.clone().project(camera),b=center.clone().add(mode==='length'?axis:mode==='thickness'?lateral:tangent).project(camera);
    const direction=new THREE.Vector2((b.x-a.x)*rect.width/2,-(b.y-a.y)*rect.height/2);
    if(direction.length()<1) direction.set(0,-Math.max(1,camera instanceof THREE.OrthographicCamera?camera.zoom:10));
    setDrag({mode,x:event.nativeEvent.clientX,y:event.nativeEvent.clientY,cut,direction});onDrag(true);gl.domElement.style.cursor='grabbing';
  };
  return <group renderOrder={20}>
    <Line points={[center,tip]} color="#e3bc42" lineWidth={2} depthTest={false}/>
    <Line points={[center,rim]} color="#71bbf0" lineWidth={2} depthTest={false}/>
    {c.shape==='rectangle' ? <Line points={[center,edge]} color="#e997c5" lineWidth={2} depthTest={false}/> : null}
    {([['position',center,'#ffffff'],['length',tip,'#e3bc42'],['diameter',rim,'#71bbf0'],...(c.shape==='rectangle' ? [['thickness',edge,'#e997c5']] : [])] as [Mode,THREE.Vector3,string][]).map(([mode,point,color],i)=><mesh key={mode} ref={mesh=>{handles.current[i]=mesh;}} position={point} renderOrder={25} onPointerDown={event=>down(mode,event)} onPointerOver={()=>{gl.domElement.style.cursor='grab';}} onPointerOut={()=>{if(!drag)gl.domElement.style.cursor='';}}>
      <sphereGeometry args={[1,12,8]}/><meshBasicMaterial color={color} transparent depthTest={false} depthWrite={false}/>
    </mesh>)}
  </group>;
}
