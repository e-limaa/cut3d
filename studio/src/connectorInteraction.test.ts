import {expect,it} from 'vitest';
import * as THREE from 'three';
import {pickConnectorPosition} from './connectorInteraction';
import type {FreeCut} from './freeCut';
const cut:FreeCut={points:[[-5,0],[5,0]],origin:[0,0,0],u:[1,0,0],v:[0,1,0],w:[0,0,1],depthMin:-5,depthMax:5,kerf:.1,rails:{front:[[-5,0,5],[5,0,5]],back:[[-5,0,-5],[5,0,-5]]}};
it('moves the connector to the mouse position on the cut surface',()=>{
  const ray=new THREE.Ray(new THREE.Vector3(2,10,-1),new THREE.Vector3(0,-1,0));
  const result=pickConnectorPosition(cut,ray)!;
  expect(result.along).toBeCloseTo(.7);expect(result.across).toBeCloseTo(.6);
});
it('does not release a connector into empty space when the mouse misses',()=>{
  expect(pickConnectorPosition(cut,new THREE.Ray(new THREE.Vector3(20,10,0),new THREE.Vector3(0,-1,0)))).toBeNull();
});
